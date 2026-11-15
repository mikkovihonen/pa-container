use anyhow::{Context, Result};
use clap::Parser;
use pa_core::guest::{
    apply_firewall, build_bwrap_args, build_sandbox_exec_command, ensure_agent_user,
    generate_nftables_conf, generate_pf_conf, AgentFirewallRule, GitVaultManager, IOSRunnerDaemon,
};
use serde_json::json;
use std::collections::{BTreeMap, HashMap};
use std::fs;
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;

pub const DEFAULT_SOCKET_PATH: &str = "/var/run/pa-agentd.sock";

#[derive(Parser, Debug)]
#[command(
    name = "pa-agentd",
    version,
    about = "PA-Container 2.0 In-Guest Control Plane Daemon"
)]
pub struct Cli {
    #[arg(long, help = "Run in stdio mode (for SSH control channels)")]
    pub stdio: bool,

    #[arg(long, default_value = DEFAULT_SOCKET_PATH, help = "Path to Unix domain socket")]
    pub socket: PathBuf,

    #[arg(long, help = "Execute a single JSON-RPC call and exit")]
    pub r#exec: Option<String>,

    #[arg(long, help = "Path to Git Vault root directory")]
    pub vault_root: Option<PathBuf>,
}

pub struct GuestDaemonService {
    pub vault_manager: GitVaultManager,
    pub ios_runner: IOSRunnerDaemon,
    pub active_processes: Mutex<HashMap<String, Child>>,
}

impl GuestDaemonService {
    pub fn new(vault_root: Option<PathBuf>) -> Self {
        Self {
            vault_manager: GitVaultManager::new(vault_root),
            ios_runner: IOSRunnerDaemon::default(),
            active_processes: Mutex::new(HashMap::new()),
        }
    }

    pub fn dispatch(&self, request: &serde_json::Value) -> serde_json::Value {
        let req_id = request.get("id").cloned().unwrap_or(json!(null));
        let method = match request.get("method").and_then(|m| m.as_str()) {
            Some(m) => m,
            None => {
                return json!({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": { "code": -32600, "message": "Invalid Request" }
                });
            }
        };

        let params = request.get("params").cloned().unwrap_or(json!({}));

        let result = match method {
            "ping" => self.rpc_ping(),
            "provision_user" => self.rpc_provision_user(&params),
            "provision_packages" => self.rpc_provision_packages(&params),
            "update_firewall" => self.rpc_update_firewall(&params),
            "init_vault" => self.rpc_init_vault(&params),
            "cow_clone" => self.rpc_cow_clone(&params),
            "launch_agent" => self.rpc_launch_agent(&params),
            "get_status" => self.rpc_get_status(),
            "stop_agent" => self.rpc_stop_agent(&params),
            "ios_create_sim" => self.rpc_ios_create_sim(&params),
            "ios_launch_app" => self.rpc_ios_launch_app(&params),
            "ios_screenshot" => self.rpc_ios_screenshot(&params),
            "ios_delete_sim" => self.rpc_ios_delete_sim(&params),
            "resize_disk" => self.rpc_resize_disk(),
            "prune_caches" => self.rpc_prune_caches(),
            "apply_tuning" => self.rpc_apply_tuning(),
            _ => {
                return json!({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": { "code": -32601, "message": format!("Method not found: {}", method) }
                });
            }
        };

        match result {
            Ok(val) => json!({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": val,
            }),
            Err(e) => json!({
                "jsonrpc": "2.0",
                "id": req_id,
                "error": { "code": -32000, "message": e.to_string() }
            }),
        }
    }

    fn rpc_ping(&self) -> Result<serde_json::Value> {
        Ok(json!({
            "status": "ok",
            "platform": std::env::consts::OS,
        }))
    }

    fn rpc_provision_user(&self, params: &serde_json::Value) -> Result<serde_json::Value> {
        let username = params
            .get("username")
            .and_then(|u| u.as_str())
            .context("Missing username")?;
        let uid = params.get("uid").and_then(|u| u.as_u64()).unwrap_or(2001) as u32;
        let home_base = params.get("home_base").and_then(|h| h.as_str());

        let home = ensure_agent_user(username, uid, home_base.map(Path::new), false)?;

        Ok(json!({
            "user": username,
            "uid": uid,
            "home": home.to_str().unwrap_or(""),
        }))
    }

    fn rpc_provision_packages(&self, params: &serde_json::Value) -> Result<serde_json::Value> {
        let packages: Vec<String> = match params.get("packages").and_then(|p| p.as_array()) {
            Some(arr) => arr
                .iter()
                .filter_map(|v| v.as_str().map(|s| s.to_string()))
                .collect(),
            None => Vec::new(),
        };

        if packages.is_empty() {
            return Ok(json!({
                "status": "ok",
                "installed": [],
            }));
        }

        if cfg!(target_os = "macos") {
            let brew_path = if Path::new("/opt/homebrew/bin/brew").exists() {
                "/opt/homebrew/bin/brew"
            } else if Path::new("/usr/local/bin/brew").exists() {
                "/usr/local/bin/brew"
            } else {
                "brew"
            };

            let mut cmd = if nix::unistd::geteuid().is_root() {
                let mut c = Command::new("sudo");
                c.args(["-u", "admin", "-i", brew_path, "install"]);
                c
            } else {
                let mut c = Command::new(brew_path);
                c.arg("install");
                c
            };
            cmd.env("HOMEBREW_NO_ANALYTICS", "1")
                .env("HOMEBREW_NO_AUTO_UPDATE", "1")
                .env("HOMEBREW_NO_INSTALL_CLEANUP", "1")
                .env("HOMEBREW_NO_ENV_HINTS", "1")
                .env("NONINTERACTIVE", "1");
            cmd.args(&packages);

            let out = cmd.output().with_context(|| {
                format!(
                    "Failed to execute Homebrew package installation for {:?}",
                    packages
                )
            })?;

            if !out.status.success() {
                anyhow::bail!(
                    "brew install failed (code {:?}): {}",
                    out.status.code(),
                    String::from_utf8_lossy(&out.stderr)
                );
            }
        } else {
            let mut cmd = Command::new("dnf");
            cmd.args(["install", "-y"]).args(&packages);

            let out = cmd.output().with_context(|| {
                format!(
                    "Failed to execute dnf package installation for {:?}",
                    packages
                )
            })?;

            if !out.status.success() {
                anyhow::bail!(
                    "dnf install failed (code {:?}): {}",
                    out.status.code(),
                    String::from_utf8_lossy(&out.stderr)
                );
            }
        }

        Ok(json!({
            "status": "ok",
            "installed": packages,
        }))
    }

    fn rpc_update_firewall(&self, params: &serde_json::Value) -> Result<serde_json::Value> {
        let proxy_ip = params
            .get("proxy_ip")
            .and_then(|p| p.as_str())
            .unwrap_or("127.0.0.1");
        let dns_port = params
            .get("dns_port")
            .and_then(|p| p.as_u64())
            .unwrap_or(5353) as u16;
        let control_port = params
            .get("control_port")
            .and_then(|p| p.as_u64())
            .unwrap_or(2222) as u16;

        let mut agents = Vec::new();
        if let Some(arr) = params.get("agents").and_then(|a| a.as_array()) {
            for item in arr {
                let user = item
                    .get("user")
                    .and_then(|u| u.as_str())
                    .unwrap_or("agent1")
                    .to_string();
                let proxy_port =
                    item.get("proxy_port").and_then(|p| p.as_u64()).unwrap_or(0) as u16;
                let transparent_port = item
                    .get("transparent_port")
                    .and_then(|t| t.as_u64())
                    .map(|t| t as u16);
                agents.push(AgentFirewallRule {
                    user,
                    proxy_port,
                    transparent_port,
                });
            }
        }

        let rules = if cfg!(target_os = "macos") {
            generate_pf_conf(proxy_ip, dns_port, &agents, control_port)
        } else {
            generate_nftables_conf(proxy_ip, dns_port, &agents, control_port)
        };

        let path = apply_firewall(&rules, None, false)?;

        Ok(json!({
            "status": "applied",
            "path": path.to_str().unwrap_or(""),
            "rules_len": rules.len(),
        }))
    }

    fn rpc_init_vault(&self, params: &serde_json::Value) -> Result<serde_json::Value> {
        let project_name = params
            .get("project_name")
            .and_then(|p| p.as_str())
            .context("Missing project_name")?;
        let repo_path = self.vault_manager.init_bare_vault(project_name)?;
        Ok(json!({
            "project": project_name,
            "vault_repo": repo_path.to_str().unwrap_or(""),
        }))
    }

    fn rpc_cow_clone(&self, params: &serde_json::Value) -> Result<serde_json::Value> {
        let project_name = params
            .get("project_name")
            .and_then(|p| p.as_str())
            .context("Missing project_name")?;
        let agent_id = params
            .get("agent_id")
            .and_then(|a| a.as_str())
            .context("Missing agent_id")?;
        let branch_name = params.get("branch_name").and_then(|b| b.as_str());

        let destination = if let Some(dest_str) = params.get("destination").and_then(|d| d.as_str())
        {
            PathBuf::from(dest_str)
        } else {
            let base = if cfg!(target_os = "macos") {
                PathBuf::from("/Users")
            } else {
                PathBuf::from("/home")
            };
            base.join(agent_id).join("workspace")
        };

        let cloned = self.vault_manager.cow_clone_workspace(
            project_name,
            &destination,
            agent_id,
            branch_name,
            false,
        )?;

        #[cfg(unix)]
        {
            let _ = Command::new("chown")
                .args(["-R", agent_id, cloned.to_str().unwrap_or("")])
                .status();
        }

        let branch = branch_name
            .map(|s| s.to_string())
            .unwrap_or_else(|| format!("pa/{}/task", agent_id));

        Ok(json!({
            "status": "cloned",
            "workspace": cloned.to_str().unwrap_or(""),
            "branch": branch,
        }))
    }

    fn rpc_launch_agent(&self, params: &serde_json::Value) -> Result<serde_json::Value> {
        let agent_id = params
            .get("agent_id")
            .and_then(|a| a.as_str())
            .context("Missing agent_id")?;
        let user = params
            .get("user")
            .and_then(|u| u.as_str())
            .unwrap_or(agent_id);
        let uid = params.get("uid").and_then(|u| u.as_u64()).unwrap_or(2001) as u32;
        let proxy_ip = params
            .get("proxy_ip")
            .and_then(|p| p.as_str())
            .unwrap_or("127.0.0.1");
        let proxy_port = params
            .get("proxy_port")
            .and_then(|p| p.as_u64())
            .unwrap_or(0) as u16;
        let socket_path = params
            .get("socket_path")
            .and_then(|s| s.as_str())
            .map(|s| s.to_string());

        let mut command: Vec<String> = match params.get("command").and_then(|c| c.as_array()) {
            Some(arr) => arr
                .iter()
                .filter_map(|v| v.as_str().map(|s| s.to_string()))
                .collect(),
            None => vec!["pa-agent-entrypoint".to_string()],
        };

        if !command.is_empty() && command[0] == "pa-agent-entrypoint" {
            let entrypoint_exists = Path::new("/opt/pa/bin/pa-agent-entrypoint").is_file()
                || Path::new("/usr/local/bin/pa-agent-entrypoint").is_file()
                || Command::new("which")
                    .arg("pa-agent-entrypoint")
                    .output()
                    .map(|o| o.status.success())
                    .unwrap_or(false);

            if !entrypoint_exists {
                let mut driver = "pi".to_string();
                let mut prompt = None;
                let mut idx = 1;
                while idx < command.len() {
                    if command[idx] == "--driver" && idx + 1 < command.len() {
                        driver = command[idx + 1].clone();
                        idx += 2;
                    } else if command[idx] == "--prompt" && idx + 1 < command.len() {
                        prompt = Some(command[idx + 1].clone());
                        idx += 2;
                    } else {
                        idx += 1;
                    }
                }
                let mut direct_cmd = vec![driver];
                if let Some(p) = prompt {
                    direct_cmd.push("--prompt".to_string());
                    direct_cmd.push(p);
                }
                command = direct_cmd;
            }
        }

        let home_dir = if let Some(h) = params.get("home_dir").and_then(|s| s.as_str()) {
            PathBuf::from(h)
        } else {
            let base = if cfg!(target_os = "macos") {
                PathBuf::from("/Users")
            } else {
                PathBuf::from("/home")
            };
            base.join(user)
        };

        let mut extra_write_paths: Vec<String> =
            match params.get("write_paths").and_then(|w| w.as_array()) {
                Some(arr) => arr
                    .iter()
                    .filter_map(|v| v.as_str().map(|s| s.to_string()))
                    .collect(),
                None => Vec::new(),
            };
        if let Some(sp) = socket_path {
            if !extra_write_paths.contains(&sp) {
                extra_write_paths.push(sp);
            }
        }
        let extra_read_paths: Vec<String> =
            match params.get("read_paths").and_then(|r| r.as_array()) {
                Some(arr) => arr
                    .iter()
                    .filter_map(|v| v.as_str().map(|s| s.to_string()))
                    .collect(),
                None => Vec::new(),
            };
        let allow_gpu = params
            .get("allow_gpu")
            .and_then(|g| g.as_bool())
            .unwrap_or(false);
        let bin_dirs: Vec<String> = match params.get("bin_dirs").and_then(|b| b.as_array()) {
            Some(arr) => arr
                .iter()
                .filter_map(|v| v.as_str().map(|s| s.to_string()))
                .collect(),
            None => Vec::new(),
        };

        let wrapped_cmd = if cfg!(target_os = "macos") {
            let profile_dir = PathBuf::from("/etc/pa/profiles");
            let _ = fs::create_dir_all(&profile_dir);
            let pfile = profile_dir.join(format!("{}.sb", user));
            let content = pa_core::guest::generate_seatbelt_profile(
                user,
                proxy_ip,
                proxy_port,
                5353,
                None,
                None,
                if extra_write_paths.is_empty() {
                    None
                } else {
                    Some(&extra_write_paths)
                },
                allow_gpu,
            );
            let _ = fs::write(&pfile, content);

            let mut final_cmd = command.clone();
            let metal_opt = params.get("metal");
            let metal_enabled = metal_opt
                .and_then(|m| m.get("enabled"))
                .and_then(|e| e.as_bool())
                .unwrap_or(false);
            if allow_gpu && metal_enabled {
                let apple_family_max = metal_opt
                    .and_then(|m| m.get("apple_family_max"))
                    .and_then(|f| f.as_u64())
                    .unwrap_or(1009);
                let max_threadgroup_memory = metal_opt
                    .and_then(|m| m.get("max_threadgroup_memory"))
                    .and_then(|t| t.as_u64())
                    .unwrap_or(65536);
                let shim_path = PathBuf::from("/usr/local/lib/TartMetalCapabilities.dylib");
                if shim_path.exists() {
                    let mut env_wrapped = vec![
                        "/usr/bin/env".to_string(),
                        format!("DYLD_INSERT_LIBRARIES={}", shim_path.display()),
                        format!("TART_METAL_APPLE_FAMILY_MAX={}", apple_family_max),
                        format!(
                            "TART_METAL_MAX_THREADGROUP_MEMORY={}",
                            max_threadgroup_memory
                        ),
                    ];
                    env_wrapped.extend(final_cmd);
                    final_cmd = env_wrapped;
                }
            }
            build_sandbox_exec_command(&pfile, &final_cmd)
        } else {
            let mut env_map = BTreeMap::new();
            if let Some(obj) = params.get("extra_env").and_then(|e| e.as_object()) {
                for (k, v) in obj {
                    if let Some(s) = v.as_str() {
                        env_map.insert(k.clone(), s.to_string());
                    }
                }
            }

            let mut rw_paths = vec![home_dir.join("workspace"), PathBuf::from("/tmp")];
            for p in &extra_write_paths {
                rw_paths.push(PathBuf::from(p));
            }

            let mut ro_paths = vec![
                PathBuf::from("/usr"),
                PathBuf::from("/lib"),
                PathBuf::from("/lib64"),
                PathBuf::from("/bin"),
                PathBuf::from("/etc"),
                PathBuf::from("/opt/pa"),
            ];
            for p in &extra_read_paths {
                ro_paths.push(PathBuf::from(p));
            }

            let landlock_cmd = pa_core::guest::build_landlock_command(
                &command,
                &rw_paths,
                Some(&ro_paths),
                Some(&[format!("{}:{}", proxy_ip, proxy_port)]),
                None,
            );

            build_bwrap_args(
                user,
                &home_dir,
                proxy_ip,
                proxy_port,
                &landlock_cmd,
                None,
                Some(&env_map),
                None,
                if extra_read_paths.is_empty() {
                    None
                } else {
                    Some(&extra_read_paths)
                },
                if extra_write_paths.is_empty() {
                    None
                } else {
                    Some(&extra_write_paths)
                },
                allow_gpu,
            )
        };

        let workdir = home_dir.join("workspace");
        let cwd = if workdir.exists() { workdir } else { home_dir };

        let log_dir = cwd.join(".pa");
        let _ = fs::create_dir_all(&log_dir);
        let log_file_path = log_dir.join("agent.log");
        let out_file = fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&log_file_path)
            .unwrap_or_else(|_| {
                fs::File::create(format!("/tmp/pa-{}.log", user))
                    .unwrap_or_else(|_| fs::File::open("/dev/null").unwrap())
            });
        let err_file = out_file
            .try_clone()
            .unwrap_or_else(|_| fs::File::open("/dev/null").unwrap());

        let mut cmd = Command::new(&wrapped_cmd[0]);
        cmd.args(&wrapped_cmd[1..])
            .current_dir(&cwd)
            .stdout(Stdio::from(out_file))
            .stderr(Stdio::from(err_file));

        if let Some(obj) = params.get("extra_env").and_then(|e| e.as_object()) {
            for (k, v) in obj {
                if let Some(s) = v.as_str() {
                    cmd.env(k, s);
                }
            }
        }
        if !bin_dirs.is_empty() {
            let current_path = std::env::var("PATH").unwrap_or_else(|_| {
                "/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin:/opt/homebrew/bin".into()
            });
            let new_path = format!("{}:{}", bin_dirs.join(":"), current_path);
            cmd.env("PATH", new_path);
        }

        #[cfg(unix)]
        unsafe {
            use std::os::unix::process::CommandExt;
            let target_uid = uid;
            let target_gid = uid;
            cmd.pre_exec(move || {
                if nix::unistd::geteuid().is_root() {
                    let ret_gid = libc::setgid(target_gid as libc::gid_t);
                    if ret_gid != 0 {
                        return Err(std::io::Error::last_os_error());
                    }
                    let ret_uid = libc::setuid(target_uid as libc::uid_t);
                    if ret_uid != 0 {
                        return Err(std::io::Error::last_os_error());
                    }
                }
                Ok(())
            });
        }

        let child = cmd.spawn().with_context(|| {
            format!(
                "Failed to spawn sandboxed agent process for user '{}'",
                user
            )
        })?;

        let pid = child.id();
        self.active_processes
            .lock()
            .unwrap()
            .insert(agent_id.to_string(), child);

        Ok(json!({
            "status": "started",
            "pid": pid,
            "command": wrapped_cmd,
        }))
    }

    fn rpc_get_status(&self) -> Result<serde_json::Value> {
        let mut map = serde_json::Map::new();
        let mut procs = self.active_processes.lock().unwrap();

        for (id, child) in procs.iter_mut() {
            let (running, exit_code) = match child.try_wait() {
                Ok(None) => (true, None),
                Ok(Some(status)) => (false, status.code()),
                Err(_) => (false, None),
            };
            map.insert(
                id.clone(),
                json!({
                    "pid": child.id(),
                    "running": running,
                    "exit_code": exit_code,
                }),
            );
        }

        Ok(json!({
            "platform": std::env::consts::OS,
            "agents": map,
        }))
    }

    fn rpc_stop_agent(&self, params: &serde_json::Value) -> Result<serde_json::Value> {
        let agent_id = params
            .get("agent_id")
            .and_then(|a| a.as_str())
            .context("Missing agent_id")?;
        let mut procs = self.active_processes.lock().unwrap();
        if let Some(mut child) = procs.remove(agent_id) {
            let _ = child.kill();
            let status = child.wait()?;
            Ok(json!({
                "agent_id": agent_id,
                "stopped": true,
                "exit_code": status.code(),
            }))
        } else {
            Ok(json!({
                "agent_id": agent_id,
                "stopped": false,
                "message": "Process not found",
            }))
        }
    }

    fn rpc_ios_create_sim(&self, params: &serde_json::Value) -> Result<serde_json::Value> {
        let agent_id = params
            .get("agent_id")
            .and_then(|a| a.as_str())
            .context("Missing agent_id")?;
        let device_type = params.get("device_type").and_then(|d| d.as_str());
        let runtime = params.get("runtime").and_then(|r| r.as_str());
        let proxy_ip = params.get("proxy_ip").and_then(|p| p.as_str());
        let proxy_port = params
            .get("proxy_port")
            .and_then(|p| p.as_u64())
            .map(|p| p as u16);

        let udid = self.ios_runner.create_and_boot_simulator(
            agent_id,
            device_type,
            runtime,
            proxy_ip,
            proxy_port,
        )?;
        Ok(json!({
            "agent_id": agent_id,
            "udid": udid,
        }))
    }

    fn rpc_ios_launch_app(&self, params: &serde_json::Value) -> Result<serde_json::Value> {
        let agent_id = params
            .get("agent_id")
            .and_then(|a| a.as_str())
            .context("Missing agent_id")?;
        let app_path = params
            .get("app_path")
            .and_then(|p| p.as_str())
            .context("Missing app_path")?;
        let bundle_id = params
            .get("bundle_id")
            .and_then(|b| b.as_str())
            .context("Missing bundle_id")?;
        let proxy_ip = params.get("proxy_ip").and_then(|p| p.as_str());
        let proxy_port = params
            .get("proxy_port")
            .and_then(|p| p.as_u64())
            .map(|p| p as u16);

        self.ios_runner.install_and_launch_app(
            agent_id,
            Path::new(app_path),
            bundle_id,
            proxy_ip,
            proxy_port,
        )?;
        Ok(json!({
            "agent_id": agent_id,
            "status": "launched",
            "bundle_id": bundle_id,
        }))
    }

    fn rpc_ios_screenshot(&self, params: &serde_json::Value) -> Result<serde_json::Value> {
        let agent_id = params
            .get("agent_id")
            .and_then(|a| a.as_str())
            .context("Missing agent_id")?;
        let output_path = params
            .get("output_path")
            .and_then(|p| p.as_str())
            .context("Missing output_path")?;

        let res = self
            .ios_runner
            .capture_screenshot(agent_id, Path::new(output_path))?;
        Ok(json!({
            "agent_id": agent_id,
            "screenshot_path": res.to_str().unwrap_or(""),
        }))
    }

    fn rpc_ios_delete_sim(&self, params: &serde_json::Value) -> Result<serde_json::Value> {
        let agent_id = params
            .get("agent_id")
            .and_then(|a| a.as_str())
            .context("Missing agent_id")?;
        self.ios_runner.delete_simulator(agent_id)?;
        Ok(json!({
            "agent_id": agent_id,
            "status": "deleted",
        }))
    }

    fn rpc_resize_disk(&self) -> Result<serde_json::Value> {
        if cfg!(target_os = "macos") {
            let container = Command::new("diskutil")
                .args(["info", "/"])
                .output()
                .ok()
                .and_then(|o| {
                    let s = String::from_utf8_lossy(&o.stdout);
                    s.lines()
                        .find(|l| l.contains("Part of Whole:"))
                        .and_then(|l| l.split(':').nth(1))
                        .map(|s| s.trim().to_string())
                })
                .unwrap_or_else(|| "disk3".to_string());

            let status = Command::new("diskutil")
                .args(["apfs", "resizeContainer", &container, "0"])
                .status();
            let success = status.map(|s| s.success()).unwrap_or(false);
            Ok(json!({
                "status": "resized",
                "container": container,
                "platform": "macos",
                "success": success,
            }))
        } else {
            let _ = Command::new("growpart").args(["/dev/sda", "1"]).status();
            let status = Command::new("resize2fs").arg("/dev/sda1").status();
            let success = status.map(|s| s.success()).unwrap_or(false);
            Ok(json!({
                "status": "resized",
                "platform": "linux",
                "success": success,
            }))
        }
    }

    fn rpc_prune_caches(&self) -> Result<serde_json::Value> {
        if cfg!(target_os = "macos") {
            let container = Command::new("diskutil")
                .args(["info", "/"])
                .output()
                .ok()
                .and_then(|o| {
                    let s = String::from_utf8_lossy(&o.stdout);
                    s.lines()
                        .find(|l| l.contains("Part of Whole:"))
                        .and_then(|l| l.split(':').nth(1))
                        .map(|s| s.trim().to_string())
                })
                .unwrap_or_else(|| "disk3".to_string());

            let _ = Command::new("rm")
                .args(["-rf", "/Library/Caches/*", "/private/var/log/*"])
                .status();
            let _ = Command::new("brew")
                .args(["cleanup", "--prune=all"])
                .status();
            let _ = Command::new("diskutil")
                .args(["apfs", "defragment", &container, "enable"])
                .status();
            Ok(json!({
                "status": "pruned",
                "container": container,
                "platform": "macos",
            }))
        } else {
            let _ = Command::new("dnf").args(["clean", "all"]).status();
            let _ = Command::new("fstrim").args(["-av"]).status();
            Ok(json!({
                "status": "pruned",
                "platform": "linux",
            }))
        }
    }

    fn rpc_apply_tuning(&self) -> Result<serde_json::Value> {
        if cfg!(target_os = "macos") {
            let _ = Command::new("mdutil").args(["-a", "-i", "off"]).status();
            let _ = Command::new("mdutil").args(["-a", "-E"]).status();
            let _ = Command::new("systemsetup")
                .args(["-setcomputersleep", "Never"])
                .status();
            let _ = Command::new("systemsetup")
                .args(["-setdisplaysleep", "Never"])
                .status();
            let _ = Command::new("systemsetup")
                .args(["-setharddisksleep", "Never"])
                .status();
            let _ = Command::new("defaults")
                .args(["write", "com.apple.CrashReporter", "DialogType", "none"])
                .status();
            let _ = Command::new("spctl").arg("--global-disable").status();
            let _ = Command::new("defaults")
                .args([
                    "write",
                    "com.apple.LaunchServices",
                    "LSQuarantine",
                    "-bool",
                    "false",
                ])
                .status();
            let _ = Command::new("softwareupdate")
                .args(["--schedule", "off"])
                .status();
            let _ = Command::new("defaults")
                .args([
                    "write",
                    "com.apple.SoftwareUpdate",
                    "AutomaticCheckEnabled",
                    "-bool",
                    "false",
                ])
                .status();
            Ok(json!({
                "status": "tuned",
                "platform": "macos",
            }))
        } else {
            Ok(json!({
                "status": "tuned",
                "platform": "linux",
            }))
        }
    }
}

pub fn run_stdio_server(service: &GuestDaemonService) -> Result<()> {
    let stdin = std::io::stdin();
    let stdout = std::io::stdout();
    let mut out_handle = stdout.lock();

    for line in stdin.lock().lines() {
        let line = line?;
        let line_trimmed = line.trim();
        if line_trimmed.is_empty() {
            continue;
        }

        let res = match serde_json::from_str::<serde_json::Value>(line_trimmed) {
            Ok(req) => service.dispatch(&req),
            Err(e) => json!({
                "jsonrpc": "2.0",
                "id": null,
                "error": { "code": -32700, "message": format!("Parse error: {}", e) }
            }),
        };

        let mut res_str = serde_json::to_string(&res)?;
        res_str.push('\n');
        out_handle.write_all(res_str.as_bytes())?;
        out_handle.flush()?;
    }

    Ok(())
}

#[cfg(unix)]
pub fn run_unix_socket_server(service: &GuestDaemonService, socket_path: &Path) -> Result<()> {
    use std::os::unix::fs::PermissionsExt;
    use std::os::unix::net::UnixListener;

    if socket_path.exists() {
        let _ = fs::remove_file(socket_path);
    }
    if let Some(parent) = socket_path.parent() {
        fs::create_dir_all(parent)?;
    }

    let listener = UnixListener::bind(socket_path)
        .with_context(|| format!("Failed to bind Unix socket at {}", socket_path.display()))?;

    let _ = fs::set_permissions(socket_path, fs::Permissions::from_mode(0o660));

    for stream in listener.incoming().flatten() {
        let reader = BufReader::new(stream.try_clone()?);
        let mut writer = stream;

        for line in reader.lines().map_while(Result::ok) {
            let line_trimmed = line.trim();
            if line_trimmed.is_empty() {
                continue;
            }
            let res = match serde_json::from_str::<serde_json::Value>(line_trimmed) {
                Ok(req) => service.dispatch(&req),
                Err(e) => json!({
                    "jsonrpc": "2.0",
                    "id": null,
                    "error": { "code": -32700, "message": format!("Parse error: {}", e) }
                }),
            };
            let mut res_str = match serde_json::to_string(&res) {
                Ok(s) => s,
                Err(_) => continue,
            };
            res_str.push('\n');
            let _ = writer.write_all(res_str.as_bytes());
            let _ = writer.flush();
        }
    }

    Ok(())
}

#[cfg(not(unix))]
pub fn run_unix_socket_server(_service: &GuestDaemonService, _socket_path: &Path) -> Result<()> {
    anyhow::bail!("Unix sockets not supported on this platform");
}

fn main() -> Result<()> {
    let cli = Cli::parse();
    let service = GuestDaemonService::new(cli.vault_root);

    if let Some(exec_json) = cli.r#exec {
        let req: serde_json::Value =
            serde_json::from_str(&exec_json).context("Invalid JSON string passed to --exec")?;
        let res = service.dispatch(&req);
        println!("{}", serde_json::to_string(&res)?);
        return Ok(());
    }

    if cli.stdio {
        run_stdio_server(&service)?;
    } else {
        run_unix_socket_server(&service, &cli.socket)?;
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_guest_daemon_ping() {
        let service = GuestDaemonService::new(None);
        let req = json!({
            "jsonrpc": "2.0",
            "id": 42,
            "method": "ping",
            "params": {}
        });
        let res = service.dispatch(&req);
        assert_eq!(res["id"], 42);
        assert_eq!(res["result"]["status"], "ok");
    }

    #[test]
    fn test_guest_daemon_provision_packages_empty() {
        let service = GuestDaemonService::new(None);
        let req = json!({
            "jsonrpc": "2.0",
            "id": 43,
            "method": "provision_packages",
            "params": {
                "packages": []
            }
        });
        let res = service.dispatch(&req);
        assert_eq!(res["id"], 43);
        assert_eq!(res["result"]["status"], "ok");
        assert_eq!(res["result"]["installed"], json!([]));
    }

    #[test]
    fn test_guest_daemon_stop_agent_not_found() {
        let service = GuestDaemonService::new(None);
        let req = json!({
            "jsonrpc": "2.0",
            "id": 44,
            "method": "stop_agent",
            "params": {
                "agent_id": "nonexistent"
            }
        });
        let res = service.dispatch(&req);
        assert_eq!(res["id"], 44);
        assert_eq!(res["result"]["stopped"], false);
    }

    #[test]
    fn test_guest_daemon_get_status() {
        let service = GuestDaemonService::new(None);
        let req = json!({
            "jsonrpc": "2.0",
            "id": 45,
            "method": "get_status",
            "params": {}
        });
        let res = service.dispatch(&req);
        assert_eq!(res["id"], 45);
        assert!(res["result"]["agents"].is_object());
    }

    #[test]
    fn test_guest_daemon_resize_disk() {
        let service = GuestDaemonService::new(None);
        let req = json!({
            "jsonrpc": "2.0",
            "id": 46,
            "method": "resize_disk",
            "params": {}
        });
        let res = service.dispatch(&req);
        assert_eq!(res["id"], 46);
        assert_eq!(res["result"]["status"], "resized");
    }

    #[test]
    fn test_guest_daemon_prune_caches() {
        let service = GuestDaemonService::new(None);
        let req = json!({
            "jsonrpc": "2.0",
            "id": 47,
            "method": "prune_caches",
            "params": {}
        });
        let res = service.dispatch(&req);
        assert_eq!(res["id"], 47);
        assert_eq!(res["result"]["status"], "pruned");
    }

    #[test]
    fn test_guest_daemon_apply_tuning() {
        let service = GuestDaemonService::new(None);
        let req = json!({
            "jsonrpc": "2.0",
            "id": 48,
            "method": "apply_tuning",
            "params": {}
        });
        let res = service.dispatch(&req);
        assert_eq!(res["id"], 48);
        assert_eq!(res["result"]["status"], "tuned");
    }

    #[test]
    fn test_guest_daemon_launch_agent_missing_id() {
        let service = GuestDaemonService::new(None);
        let req = json!({
            "jsonrpc": "2.0",
            "id": 49,
            "method": "launch_agent",
            "params": {
                "command": ["echo", "test"]
            }
        });
        let res = service.dispatch(&req);
        assert_eq!(res["id"], 49);
        assert!(res["error"].is_object());
    }
}
