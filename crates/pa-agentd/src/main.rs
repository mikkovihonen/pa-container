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
            "update_firewall" => self.rpc_update_firewall(&params),
            "init_vault" => self.rpc_init_vault(&params),
            "cow_clone" => self.rpc_cow_clone(&params),
            "launch_agent" => self.rpc_launch_agent(&params),
            "get_status" => self.rpc_get_status(),
            "ios_create_sim" => self.rpc_ios_create_sim(&params),
            "ios_launch_app" => self.rpc_ios_launch_app(&params),
            "ios_screenshot" => self.rpc_ios_screenshot(&params),
            "ios_delete_sim" => self.rpc_ios_delete_sim(&params),
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
                let proxy_port = item
                    .get("proxy_port")
                    .and_then(|p| p.as_u64())
                    .unwrap_or(8081) as u16;
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
            .unwrap_or(8081) as u16;

        let command: Vec<String> = match params.get("command").and_then(|c| c.as_array()) {
            Some(arr) => arr
                .iter()
                .filter_map(|v| v.as_str().map(|s| s.to_string()))
                .collect(),
            None => vec!["pa-agent-entrypoint".to_string()],
        };

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

        let wrapped_cmd = if cfg!(target_os = "macos") {
            let profile_dir = PathBuf::from("/etc/pa/profiles");
            let _ = fs::create_dir_all(&profile_dir);
            let pfile = profile_dir.join(format!("{}.sb", user));
            let content = pa_core::guest::generate_seatbelt_profile(
                user, proxy_ip, proxy_port, 5353, None, None,
            );
            let _ = fs::write(&pfile, content);
            build_sandbox_exec_command(&pfile, &command)
        } else {
            let mut env_map = BTreeMap::new();
            if let Some(obj) = params.get("extra_env").and_then(|e| e.as_object()) {
                for (k, v) in obj {
                    if let Some(s) = v.as_str() {
                        env_map.insert(k.clone(), s.to_string());
                    }
                }
            }
            build_bwrap_args(
                user,
                &home_dir,
                proxy_ip,
                proxy_port,
                &command,
                None,
                Some(&env_map),
                None,
            )
        };

        let workdir = home_dir.join("workspace");
        let cwd = if workdir.exists() { workdir } else { home_dir };

        let mut cmd = Command::new(&wrapped_cmd[0]);
        cmd.args(&wrapped_cmd[1..])
            .current_dir(&cwd)
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());

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
            let running = matches!(child.try_wait(), Ok(None));
            map.insert(
                id.clone(),
                json!({
                    "pid": child.id(),
                    "running": running,
                }),
            );
        }

        Ok(json!({
            "platform": std::env::consts::OS,
            "agents": map,
        }))
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
}
