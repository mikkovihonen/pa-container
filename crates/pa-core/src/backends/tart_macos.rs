use anyhow::{Context, Result};
use serde_json::json;
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

use crate::backend::FactoryBackend;
use crate::schema::{resolve_agent_sockets, AgentSpec, FactoryConfig};

pub const DEFAULT_TART_VM: &str = "pa-factory-macos";
pub const DEFAULT_TART_GATEWAY: &str = "192.168.64.1";

pub struct TartMacOSBackend {
    pub config: Option<FactoryConfig>,
    pub vm_name: String,
    pub proxy_host_ip: String,
    pub ssh_user: String,
    pub ssh_port: u16,
    pub project_name: std::sync::Mutex<String>,
}

impl TartMacOSBackend {
    pub fn new(
        config: Option<FactoryConfig>,
        vm_name: Option<String>,
        proxy_host_ip: Option<String>,
        ssh_user: Option<String>,
        ssh_port: Option<u16>,
    ) -> Self {
        Self {
            config,
            vm_name: vm_name.unwrap_or_else(|| DEFAULT_TART_VM.to_string()),
            proxy_host_ip: proxy_host_ip.unwrap_or_else(|| DEFAULT_TART_GATEWAY.to_string()),
            ssh_user: ssh_user.unwrap_or_else(|| "admin".to_string()),
            ssh_port: ssh_port.unwrap_or(22),
            project_name: std::sync::Mutex::new("project".to_string()),
        }
    }

    pub fn apply_host_metal_config(metal: &crate::schema::MetalSpec) -> Result<()> {
        if !metal.enabled {
            return Ok(());
        }
        #[cfg(target_os = "macos")]
        {
            match metal.host_mode.to_lowercase().as_str() {
                "ephemeral" => {
                    let check = Command::new("defaults")
                        .args([
                            "read",
                            "com.apple.gpusw.ParavirtualizedGraphics",
                            "ForceUnrestrictedDeviceFeatureLevel",
                        ])
                        .output();
                    let already_enabled = match check {
                        Ok(out) => String::from_utf8_lossy(&out.stdout).trim() == "1",
                        Err(_) => false,
                    };
                    if !already_enabled {
                        let res = Command::new("defaults")
                            .args([
                                "write",
                                "com.apple.gpusw.ParavirtualizedGraphics",
                                "ForceUnrestrictedDeviceFeatureLevel",
                                "-bool",
                                "true",
                            ])
                            .status()
                            .context("Failed to write host ParavirtualizedGraphics preference")?;
                        if res.success() {
                            let marker = dirs_fallback_cache().join("ephemeral_host_metal");
                            let _ = fs::write(marker, "true");
                        }
                    }
                }
                "persistent" => {
                    let _ = Command::new("defaults")
                        .args([
                            "write",
                            "com.apple.gpusw.ParavirtualizedGraphics",
                            "ForceUnrestrictedDeviceFeatureLevel",
                            "-bool",
                            "true",
                        ])
                        .status();
                    let marker = dirs_fallback_cache().join("ephemeral_host_metal");
                    let _ = fs::remove_file(marker);
                }
                "none" | "manual" => {}
                other => {
                    eprintln!("Warning: Unknown compute.metal.host_mode '{}'", other);
                }
            }
        }
        Ok(())
    }

    pub fn revert_host_metal_if_needed() -> Result<()> {
        #[cfg(target_os = "macos")]
        {
            let marker = dirs_fallback_cache().join("ephemeral_host_metal");
            if marker.exists() {
                let _ = Command::new("defaults")
                    .args([
                        "delete",
                        "com.apple.gpusw.ParavirtualizedGraphics",
                        "ForceUnrestrictedDeviceFeatureLevel",
                    ])
                    .status();
                let _ = fs::remove_file(marker);
            }
        }
        Ok(())
    }

    pub fn get_vm_ip(&self) -> Result<String> {
        if std::env::var("PA_TEST_MODE").unwrap_or_default() == "1" {
            return Ok(self.proxy_host_ip.clone());
        }

        let out = Command::new("tart")
            .args(["ip", &self.vm_name])
            .output()
            .with_context(|| format!("Failed to run tart ip for '{}'", self.vm_name))?;

        if !out.status.success() {
            anyhow::bail!(
                "Tart VM '{}' is not running or has not acquired an IP address: {}",
                self.vm_name,
                String::from_utf8_lossy(&out.stderr)
            );
        }

        let ip = String::from_utf8_lossy(&out.stdout).trim().to_string();
        if ip.is_empty() {
            anyhow::bail!("Tart VM '{}' returned empty IP", self.vm_name);
        }
        Ok(ip)
    }

    pub fn execute_ssh_rpc(
        &self,
        method: &str,
        params: serde_json::Value,
    ) -> Result<serde_json::Value> {
        if std::env::var("PA_TEST_MODE").unwrap_or_default() == "1" {
            return Ok(json!({ "result": "mock_success" }));
        }

        let vm_ip = self.get_vm_ip()?;
        let payload = json!({
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params,
        });
        let payload_str = serde_json::to_string(&payload)?;

        let mut child_cmd = Command::new("ssh");
        let id_factory = dirs_fallback_cache().join("id_factory");
        if id_factory.exists() {
            child_cmd.args([
                "-i",
                &id_factory.to_string_lossy(),
                "-o",
                "IdentitiesOnly=yes",
            ]);
        }
        let mut ssh_args = vec![
            "-p".to_string(),
            self.ssh_port.to_string(),
            "-o".to_string(),
            "StrictHostKeyChecking=no".to_string(),
            "-o".to_string(),
            "UserKnownHostsFile=/dev/null".to_string(),
            "-o".to_string(),
            "ConnectTimeout=5".to_string(),
            format!("{}@{}", self.ssh_user, vm_ip),
        ];
        if self.ssh_user != "root" {
            ssh_args.push("sudo".to_string());
        }
        ssh_args.push("pa-agentd".to_string());
        ssh_args.push("--stdio".to_string());

        let mut child = child_cmd
            .args(&ssh_args)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .with_context(|| {
                format!("Failed to spawn SSH process to {}@{}", self.ssh_user, vm_ip)
            })?;

        if let Some(mut stdin) = child.stdin.take() {
            stdin.write_all(payload_str.as_bytes())?;
            stdin.write_all(b"\n")?;
        }

        let output = child.wait_with_output()?;
        if !output.status.success() {
            anyhow::bail!(
                "SSH RPC error for method '{}': {}",
                method,
                String::from_utf8_lossy(&output.stderr)
            );
        }

        let stdout_str = String::from_utf8_lossy(&output.stdout);
        let resp: serde_json::Value = serde_json::from_str(stdout_str.trim())
            .with_context(|| format!("Invalid JSON-RPC response from guest: {}", stdout_str))?;

        if let Some(err) = resp.get("error") {
            anyhow::bail!("JSON-RPC returned error for {}: {}", method, err);
        }

        Ok(resp)
    }
}

impl FactoryBackend for TartMacOSBackend {
    fn start_proxy(&self, config: &FactoryConfig) -> Result<String> {
        let cache_dir = dirs_fallback_cache();
        let sockets_dir = cache_dir.join("sockets");
        fs::create_dir_all(&sockets_dir)?;
        let mut config_clone = config.clone();
        crate::compute::inject_compute_endpoints_to_allowlist(&mut config_clone);
        let agents = resolve_agent_sockets(&config_clone.agents, &sockets_dir);
        let nonce = crate::manifest::generate_session_nonce();
        let mut proxy_rules = Vec::new();

        for a in &agents {
            let mut placeholders = serde_json::Map::new();
            for tok_name in &a.tokens {
                let rule = crate::manifest::TokenRuleSpec {
                    env_var: tok_name.clone(),
                    keyring_service: None,
                    keyring_key: None,
                    allowed_hosts: a.allowlist.clone(),
                };
                let placeholder =
                    crate::manifest::derive_placeholder_token(&nonce, &a.id, tok_name);
                if let Some(secret) = rule.resolve_secret() {
                    placeholders.insert(placeholder, json!(&*secret));
                } else {
                    placeholders.insert(placeholder, json!(""));
                }
            }

            let sock_path = a
                .socket_path
                .as_ref()
                .map(|s| s.to_string_lossy().to_string())
                .unwrap_or_else(|| format!("{}/{}.sock", sockets_dir.display(), a.id));
            let flow_log_path = cache_dir.join(format!("flows-agent-{}.jsonl", a.id));

            proxy_rules.push(json!({
                "id": a.id,
                "agent_id": a.id,
                "user": a.id,
                "driver": a.driver,
                "socket_path": sock_path,
                "host_socket_path": sock_path,
                "proxy_port": a.proxy_port,
                "transparent_port": a.transparent_port,
                "allowed_hosts": a.allowlist,
                "token_placeholders": placeholders,
                "flow_log_path": flow_log_path.to_string_lossy().to_string(),
            }));
        }

        let proxy_config_path = cache_dir.join("multi_agent_proxy.json");
        fs::create_dir_all(&cache_dir)?;
        fs::write(
            &proxy_config_path,
            serde_json::to_string_pretty(&json!({ "agents": proxy_rules }))?,
        )?;

        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let _ = fs::set_permissions(&proxy_config_path, fs::Permissions::from_mode(0o600));
        }

        let _ =
            crate::backend::ensure_proxy_server(&self.proxy_host_ip, &proxy_config_path, &agents);

        Ok(self.proxy_host_ip.clone())
    }

    fn ensure_factory_vm(&self, config: &FactoryConfig, _proxy_ip: &str) -> Result<()> {
        if std::env::var("PA_TEST_MODE").unwrap_or_default() == "1" {
            return Ok(());
        }
        if config.compute.metal.enabled {
            Self::apply_host_metal_config(&config.compute.metal)?;
        }
        let ip_check = self.get_vm_ip();
        if ip_check.is_err() {
            let get_out = Command::new("tart").args(["get", &self.vm_name]).output();
            if get_out.is_err() || !get_out.unwrap().status.success() {
                if std::env::var("PA_TEST_MODE").unwrap_or_default() == "1" {
                    return Ok(());
                }
                anyhow::bail!(
                    "Tart VM '{}' does not exist. Please create the VM first (e.g. `tart create {} --from-ipsw latest` or `tart clone <base-image> {}`).",
                    self.vm_name,
                    self.vm_name,
                    self.vm_name
                );
            }

            let mut cmd = Command::new("nohup");
            cmd.args([
                "tart",
                "run",
                "--no-graphics",
                "--no-clipboard",
                "--no-audio",
                &self.vm_name,
            ])
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null());

            #[cfg(unix)]
            {
                use std::os::unix::process::CommandExt;
                cmd.process_group(0);
            }

            let mut child = cmd
                .spawn()
                .with_context(|| format!("Failed to spawn Tart VM '{}'", self.vm_name))?;

            let start = std::time::Instant::now();
            let mut acquired_ip = None;
            while start.elapsed() < std::time::Duration::from_secs(60) {
                if let Ok(Some(status)) = child.try_wait() {
                    anyhow::bail!(
                        "Tart VM '{}' exited prematurely with code: {:?}",
                        self.vm_name,
                        status.code()
                    );
                }
                if let Ok(ip) = self.get_vm_ip() {
                    acquired_ip = Some(ip);
                    break;
                }
                std::thread::sleep(std::time::Duration::from_millis(500));
            }

            if acquired_ip.is_none() {
                anyhow::bail!(
                    "Tart VM '{}' failed to acquire an IP address within 60 seconds",
                    self.vm_name
                );
            }
        }

        // Wait for SSH readiness (up to 60s for cold boot)
        let vm_ip = self.get_vm_ip()?;
        let id_factory = dirs_fallback_cache().join("id_factory");
        let start_ssh = std::time::Instant::now();
        let mut ssh_ready = false;
        while start_ssh.elapsed() < std::time::Duration::from_secs(60) {
            let mut test_cmd = Command::new("ssh");
            if id_factory.exists() {
                test_cmd.args([
                    "-i",
                    &id_factory.to_string_lossy(),
                    "-o",
                    "IdentitiesOnly=yes",
                ]);
            }
            let res = test_cmd
                .args([
                    "-p",
                    &self.ssh_port.to_string(),
                    "-o",
                    "StrictHostKeyChecking=no",
                    "-o",
                    "UserKnownHostsFile=/dev/null",
                    "-o",
                    "ConnectTimeout=2",
                    &format!("{}@{}", self.ssh_user, vm_ip),
                    "echo",
                    "ready",
                ])
                .output();
            if let Ok(out) = res {
                if out.status.success() {
                    ssh_ready = true;
                    break;
                }
            }
            std::thread::sleep(std::time::Duration::from_millis(500));
        }

        if !ssh_ready {
            anyhow::bail!(
                "Tart VM '{}' failed to accept SSH connections",
                self.vm_name
            );
        }

        let _ = self.execute_ssh_rpc("apply_tuning", json!({}));
        let _ = self.execute_ssh_rpc("resize_disk", json!({}));

        Ok(())
    }

    fn sync_git_to_vault(&self, host_repo: &Path, branch: &str) -> Result<String> {
        let project_name = host_repo
            .file_name()
            .and_then(|s| s.to_str())
            .unwrap_or("project");

        *self.project_name.lock().unwrap() = project_name.to_string();

        if std::env::var("PA_TEST_MODE").unwrap_or_default() == "1" {
            let rev_out = Command::new("git")
                .args(["rev-parse", "HEAD"])
                .current_dir(host_repo)
                .output()
                .context("Failed to get HEAD commit in test mode")?;
            return Ok(String::from_utf8_lossy(&rev_out.stdout).trim().to_string());
        }

        let vm_ip = self.get_vm_ip()?;
        self.execute_ssh_rpc("init_vault", json!({ "project_name": project_name }))?;

        let vault_git_url = format!(
            "ssh://{}@{}:{}/var/pa-vault/{}.git",
            self.ssh_user, vm_ip, self.ssh_port, project_name
        );

        let stash_out = Command::new("git")
            .args(["stash", "create"])
            .current_dir(host_repo)
            .output();

        let commit_to_push = if let Ok(out) = stash_out {
            if out.status.success() {
                let s = String::from_utf8_lossy(&out.stdout).trim().to_string();
                if !s.is_empty() {
                    s
                } else {
                    branch.to_string()
                }
            } else {
                branch.to_string()
            }
        } else {
            branch.to_string()
        };

        let mut push_cmd = Command::new("git");
        let id_factory = dirs_fallback_cache().join("id_factory");
        if id_factory.exists() {
            push_cmd.env(
                "GIT_SSH_COMMAND",
                format!(
                    "ssh -i {} -o IdentitiesOnly=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null",
                    id_factory.display()
                ),
            );
        }
        let out = push_cmd
            .args([
                "push",
                "-f",
                &vault_git_url,
                &format!("+{}:refs/heads/main", commit_to_push),
            ])
            .current_dir(host_repo)
            .output()
            .with_context(|| {
                format!("Failed to push repository to VM vault at {}", vault_git_url)
            })?;

        if !out.status.success() {
            anyhow::bail!(
                "git push to vault failed: {}",
                String::from_utf8_lossy(&out.stderr)
            );
        }

        let rev_out = Command::new("git")
            .args(["rev-parse", "HEAD"])
            .current_dir(host_repo)
            .output()
            .context("Failed to get HEAD commit")?;

        Ok(String::from_utf8_lossy(&rev_out.stdout).trim().to_string())
    }

    fn provision_packages(&self, packages: &[String]) -> Result<()> {
        if packages.is_empty() {
            return Ok(());
        }
        let res = self.execute_ssh_rpc(
            "provision_packages",
            json!({
                "packages": packages,
            }),
        )?;
        if res.get("result").is_some() {
            Ok(())
        } else {
            anyhow::bail!("Package provisioning failed on macOS Tart guest: {:?}", res);
        }
    }

    fn provision_capabilities(&self, caps: &crate::manifest::ResolvedCapabilities) -> Result<()> {
        self.provision_packages(&caps.macos_brew_packages)
    }

    fn launch_agent(
        &self,
        agent: &AgentSpec,
        task_prompt: Option<&str>,
        capabilities: Option<&crate::manifest::ResolvedCapabilities>,
    ) -> Result<i32> {
        if std::env::var("PA_TEST_MODE").unwrap_or_default() == "1" {
            return Ok(0);
        }

        self.execute_ssh_rpc(
            "provision_user",
            json!({
                "username": agent.id,
                "uid": agent.uid,
            }),
        )?;

        let socket_file = agent
            .socket_path
            .as_ref()
            .map(|s| s.to_string_lossy().to_string())
            .unwrap_or_else(|| format!("{}.sock", agent.id));

        let agents_data = vec![json!({
            "id": agent.id,
            "user": agent.id,
            "socket_path": socket_file,
            "proxy_port": agent.proxy_port.unwrap_or(0),
            "transparent_port": agent.transparent_port,
        })];

        self.execute_ssh_rpc(
            "update_firewall",
            json!({
                "proxy_ip": self.proxy_host_ip,
                "dns_port": 5353,
                "control_port": self.ssh_port,
                "agents": agents_data,
            }),
        )?;

        let project_name = self.project_name.lock().unwrap().clone();
        self.execute_ssh_rpc(
            "cow_clone",
            json!({
                "project_name": project_name,
                "agent_id": agent.id,
                "branch_name": format!("{}/task", agent.branch_prefix),
            }),
        )?;

        let mut cmd = vec![
            "pa-agent-entrypoint".to_string(),
            "--driver".to_string(),
            agent.driver.clone(),
        ];
        if let Some(prompt) = task_prompt {
            cmd.push("--prompt".to_string());
            cmd.push(prompt.to_string());
        }

        let mut payload = json!({
            "agent_id": agent.id,
            "command": cmd,
            "user": agent.id,
            "uid": agent.uid,
            "socket_path": socket_file,
            "proxy_ip": self.proxy_host_ip,
            "proxy_port": agent.proxy_port.unwrap_or(0),
        });

        let nonce = crate::manifest::generate_session_nonce();
        let mut env_map = serde_json::Map::new();

        if let Some(caps) = capabilities {
            for (k, v) in &caps.env {
                env_map.insert(k.clone(), json!(v));
            }
            payload["bin_dirs"] = json!(caps.bin_dirs);
            payload["read_paths"] = json!(caps.read_paths);
            payload["write_paths"] = json!(caps.write_paths);
            payload["allow_gpu"] = json!(caps.allow_gpu);
        }

        for tok in &agent.tokens {
            let ph = crate::manifest::derive_placeholder_token(&nonce, &agent.id, tok);
            env_map.insert(tok.clone(), json!(ph));
        }
        payload["extra_env"] = json!(env_map);

        let metal_spec = self.config.as_ref().map(|c| &c.compute.metal);
        let metal_enabled = metal_spec.map(|m| m.enabled).unwrap_or(false);
        if metal_enabled {
            payload["metal"] = json!({
                "enabled": true,
                "apple_family_max": metal_spec.map(|m| m.apple_family_max).unwrap_or(1009),
                "max_threadgroup_memory": metal_spec.map(|m| m.max_threadgroup_memory).unwrap_or(65536),
            });
        }

        let res = self.execute_ssh_rpc("launch_agent", payload)?;

        if let Some(code) = res
            .get("result")
            .and_then(|r| r.get("exit_code"))
            .and_then(|c| c.as_i64())
        {
            Ok(code as i32)
        } else if res.get("result").is_some() {
            Ok(0)
        } else {
            anyhow::bail!("Failed to launch agent '{}': {:?}", agent.id, res);
        }
    }

    fn fetch_agent_branch(&self, agent_id: &str, host_repo: &Path) -> Result<PathBuf> {
        let worktree_path = host_repo.join(".pa").join("review").join(agent_id);
        if std::env::var("PA_TEST_MODE").unwrap_or_default() == "1" {
            let _ = fs::create_dir_all(&worktree_path);
            return Ok(worktree_path);
        }

        let project_name = host_repo
            .file_name()
            .and_then(|s| s.to_str())
            .unwrap_or("project");

        let vm_ip = self.get_vm_ip()?;
        let vault_git_url = format!(
            "ssh://{}@{}:{}/var/pa-vault/{}.git",
            self.ssh_user, vm_ip, self.ssh_port, project_name
        );
        let worktree_path = host_repo.join(".pa").join("review").join(agent_id);

        let mut fetch_cmd = Command::new("git");
        let id_factory = dirs_fallback_cache().join("id_factory");
        if id_factory.exists() {
            fetch_cmd.env(
                "GIT_SSH_COMMAND",
                format!(
                    "ssh -i {} -o IdentitiesOnly=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null",
                    id_factory.display()
                ),
            );
        }
        let out = fetch_cmd
            .args([
                "fetch",
                &vault_git_url,
                &format!("+refs/heads/pa/{0}/*:refs/remotes/pa/{0}/*", agent_id),
            ])
            .current_dir(host_repo)
            .output()
            .with_context(|| format!("Failed to fetch agent branch from {}", vault_git_url))?;

        if !out.status.success() {
            anyhow::bail!("git fetch failed: {}", String::from_utf8_lossy(&out.stderr));
        }

        if worktree_path.exists() {
            let branch = format!("pa/{}/task", agent_id);
            let _ = Command::new("git")
                .args(["checkout", &branch])
                .current_dir(&worktree_path)
                .output();
            let _ = Command::new("git")
                .args([
                    "reset",
                    "--hard",
                    &format!("refs/remotes/pa/{}/task", agent_id),
                ])
                .current_dir(&worktree_path)
                .output();
        } else {
            if let Some(p) = worktree_path.parent() {
                let _ = fs::create_dir_all(p);
            }
            let _ = Command::new("git")
                .args(["worktree", "prune"])
                .current_dir(host_repo)
                .output();
            let branch = format!("pa/{}/task", agent_id);
            let branch_exists = Command::new("git")
                .args(["rev-parse", "--verify", &branch])
                .current_dir(host_repo)
                .output()
                .map(|o| o.status.success())
                .unwrap_or(false);

            let mut add_cmd = Command::new("git");
            add_cmd.args(["worktree", "add"]);
            if !branch_exists {
                add_cmd.args(["-b", &branch]);
            }
            add_cmd.arg(worktree_path.to_str().unwrap_or(""));
            if branch_exists {
                add_cmd.arg(&branch);
            }

            let add_out = add_cmd
                .current_dir(host_repo)
                .output()
                .context("Failed to add git worktree")?;

            if !add_out.status.success() {
                anyhow::bail!(
                    "git worktree add failed: {}",
                    String::from_utf8_lossy(&add_out.stderr)
                );
            }
        }

        Ok(worktree_path)
    }

    fn stop_factory(&self) -> Result<()> {
        let _ = crate::backend::stop_proxy_server();
        let _ = Self::revert_host_metal_if_needed();
        if std::env::var("PA_TEST_MODE").unwrap_or_default() == "1" {
            return Ok(());
        }
        if self.get_vm_ip().is_ok() {
            let _ = self.execute_ssh_rpc("prune_caches", json!({}));
            let status = Command::new("tart")
                .args(["stop", &self.vm_name])
                .status()
                .with_context(|| format!("Failed to stop Tart VM '{}'", self.vm_name))?;

            if !status.success() {
                anyhow::bail!("tart stop failed for VM '{}'", self.vm_name);
            }
        }
        Ok(())
    }

    fn get_status(&self) -> Result<serde_json::Value> {
        let (running, guest_data) = if self.get_vm_ip().is_ok() {
            match self.execute_ssh_rpc("get_status", json!({})) {
                Ok(rpc_res) => (true, rpc_res.get("result").cloned().unwrap_or(json!({}))),
                Err(_) => (false, json!({ "status": "stopped" })),
            }
        } else {
            (false, json!({ "status": "stopped" }))
        };
        Ok(json!({
            "backend": "macos-tart",
            "vm_name": self.vm_name,
            "running": running,
            "proxy_host_ip": self.proxy_host_ip,
            "guest": guest_data,
        }))
    }
}

fn dirs_fallback_cache() -> PathBuf {
    if let Ok(home) = std::env::var("HOME") {
        PathBuf::from(home).join(".cache").join("pa-container")
    } else {
        std::env::temp_dir().join("pa-container")
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_tart_backend_defaults() {
        let backend = TartMacOSBackend::new(None, None, None, None, None);
        assert_eq!(backend.vm_name, DEFAULT_TART_VM);
        assert_eq!(backend.proxy_host_ip, DEFAULT_TART_GATEWAY);
    }

    #[test]
    fn test_tart_start_proxy() {
        let backend = TartMacOSBackend::new(None, None, None, None, None);
        let cfg = FactoryConfig::default();
        let ip = backend.start_proxy(&cfg).unwrap();
        assert_eq!(ip, DEFAULT_TART_GATEWAY);
        crate::backend::assert_backend_conformance(&backend, &cfg);
    }

    #[test]
    fn test_apply_host_metal_config_disabled() {
        let metal = crate::schema::MetalSpec {
            enabled: false,
            host_mode: "ephemeral".to_string(),
            apple_family_max: 1009,
            max_threadgroup_memory: 65536,
        };
        let res = TartMacOSBackend::apply_host_metal_config(&metal);
        assert!(res.is_ok());
    }

    #[test]
    fn test_revert_host_metal_marker_handling() {
        let marker = dirs_fallback_cache().join("ephemeral_host_metal");
        let _ = fs::create_dir_all(dirs_fallback_cache());
        let _ = fs::remove_file(&marker);

        assert!(TartMacOSBackend::revert_host_metal_if_needed().is_ok());

        let _ = fs::write(&marker, "true");
        assert!(marker.exists());

        assert!(TartMacOSBackend::revert_host_metal_if_needed().is_ok());
        assert!(!marker.exists());
    }
}
