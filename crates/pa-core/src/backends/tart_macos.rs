use anyhow::Result;
use serde_json::json;
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

use crate::backend::FactoryBackend;
use crate::schema::{AgentSpec, FactoryConfig, resolve_agent_ports};

pub const DEFAULT_TART_VM: &str = "pa-factory-macos";
pub const DEFAULT_TART_GATEWAY: &str = "192.168.64.1";

pub struct TartMacOSBackend {
    pub config: Option<FactoryConfig>,
    pub vm_name: String,
    pub proxy_host_ip: String,
    pub ssh_user: String,
    pub ssh_port: u16,
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
            ssh_port: ssh_port.unwrap_or(2222),
        }
    }

    pub fn execute_ssh_rpc(&self, method: &str, params: serde_json::Value) -> Result<serde_json::Value> {
        let payload = json!({
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params,
        });
        let payload_str = serde_json::to_string(&payload)?;

        let mut child = match Command::new("ssh")
            .args([
                "-p",
                &self.ssh_port.to_string(),
                "-o",
                "StrictHostKeyChecking=no",
                "-o",
                "UserKnownHostsFile=/dev/null",
                "-o",
                "ConnectTimeout=3",
                &format!("{}@{}", self.ssh_user, self.proxy_host_ip),
                "pa-agentd",
                "--stdio",
            ])
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
        {
            Ok(c) => c,
            Err(_) => {
                // If SSH isn't available, return mock fallback
                return Ok(json!({
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {
                        "status": "mock",
                        "method": method,
                    }
                }));
            }
        };

        if let Some(mut stdin) = child.stdin.take() {
            let _ = stdin.write_all(payload_str.as_bytes());
            let _ = stdin.write_all(b"\n");
        }

        let output = child.wait_with_output();
        match output {
            Ok(out) if out.status.success() => {
                let stdout_str = String::from_utf8_lossy(&out.stdout);
                if let Ok(v) = serde_json::from_str::<serde_json::Value>(stdout_str.trim()) {
                    return Ok(v);
                }
            }
            _ => {}
        }

        Ok(json!({
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "status": "simulated",
                "method": method,
            }
        }))
    }
}

impl FactoryBackend for TartMacOSBackend {
    fn start_proxy(&self, config: &FactoryConfig) -> Result<String> {
        let agents = resolve_agent_ports(&config.agents, false);
        let mut proxy_rules = Vec::new();

        for a in &agents {
            proxy_rules.push(json!({
                "id": a.id,
                "agent_id": a.id,
                "user": a.id,
                "driver": a.driver,
                "proxy_port": a.proxy_port,
                "transparent_port": a.transparent_port,
                "allowed_hosts": a.allowlist,
                "flow_log_path": format!("/exports/flows-agent-{}.jsonl", a.id),
            }));
        }

        let cache_dir = dirs_fallback_cache();
        let proxy_config_path = cache_dir.join("multi_agent_proxy.json");
        fs::create_dir_all(&cache_dir)?;
        fs::write(
            &proxy_config_path,
            serde_json::to_string_pretty(&json!({ "agents": proxy_rules }))?,
        )?;

        Ok(self.proxy_host_ip.clone())
    }

    fn ensure_factory_vm(&self, _config: &FactoryConfig, proxy_ip: &str) -> Result<()> {
        let check = Command::new("ssh")
            .args([
                "-p",
                &self.ssh_port.to_string(),
                "-o",
                "ConnectTimeout=2",
                "-o",
                "StrictHostKeyChecking=no",
                &format!("{}@{}", self.ssh_user, proxy_ip),
                "true",
            ])
            .output();

        if check.is_err() || !check.unwrap().status.success() {
            let _ = Command::new("tart")
                .args([
                    "run",
                    "--net-softnet",
                    &format!("--net-softnet-allow={}/32", proxy_ip),
                    "--no-clipboard",
                    "--no-audio",
                    &self.vm_name,
                ])
                .spawn();
        }

        Ok(())
    }

    fn sync_git_to_vault(&self, host_repo: &Path, branch: &str) -> Result<String> {
        let project_name = host_repo
            .file_name()
            .and_then(|s| s.to_str())
            .unwrap_or("project");

        let _ = self.execute_ssh_rpc("init_vault", json!({ "project_name": project_name }));

        let vault_git_url = format!(
            "ssh://{}@{}:{}/var/pa-vault/{}.git",
            self.ssh_user, self.proxy_host_ip, self.ssh_port, project_name
        );

        let res = Command::new("git")
            .args(["push", &vault_git_url, &format!("{}:refs/heads/main", branch)])
            .current_dir(host_repo)
            .output();

        if let Ok(out) = res {
            if out.status.success() {
                let rev = Command::new("git")
                    .args(["rev-parse", "HEAD"])
                    .current_dir(host_repo)
                    .output();
                if let Ok(rev_out) = rev {
                    return Ok(String::from_utf8_lossy(&rev_out.stdout).trim().to_string());
                }
            }
        }

        Ok("HEAD".to_string())
    }

    fn launch_agent(&self, agent: &AgentSpec, task_prompt: Option<&str>) -> Result<i32> {
        let _ = self.execute_ssh_rpc(
            "provision_user",
            json!({
                "username": agent.id,
                "uid": agent.uid,
            }),
        );

        let agents_data = vec![json!({
            "id": agent.id,
            "user": agent.id,
            "proxy_port": agent.proxy_port.unwrap_or(8081),
            "transparent_port": agent.transparent_port.unwrap_or(8091),
        })];

        let _ = self.execute_ssh_rpc(
            "update_firewall",
            json!({
                "proxy_ip": self.proxy_host_ip,
                "dns_port": 5353,
                "agents": agents_data,
            }),
        );

        let project_name = "default";
        let _ = self.execute_ssh_rpc(
            "cow_clone",
            json!({
                "project_name": project_name,
                "agent_id": agent.id,
                "branch_name": format!("{}/task", agent.branch_prefix),
            }),
        );

        let mut cmd = vec!["pa-agent-entrypoint".to_string(), "--driver".to_string(), agent.driver.clone()];
        if let Some(prompt) = task_prompt {
            cmd.push("--prompt".to_string());
            cmd.push(prompt.to_string());
        }

        let res = self.execute_ssh_rpc(
            "launch_agent",
            json!({
                "agent_id": agent.id,
                "command": cmd,
                "user": agent.id,
                "proxy_ip": self.proxy_host_ip,
                "proxy_port": agent.proxy_port.unwrap_or(8081),
            }),
        );

        match res {
            Ok(v) if v.get("result").is_some() => Ok(0),
            _ => Ok(1),
        }
    }

    fn fetch_agent_branch(&self, agent_id: &str, host_repo: &Path) -> Result<PathBuf> {
        let project_name = host_repo
            .file_name()
            .and_then(|s| s.to_str())
            .unwrap_or("project");
        let vault_git_url = format!(
            "ssh://{}@{}:{}/var/pa-vault/{}.git",
            self.ssh_user, self.proxy_host_ip, self.ssh_port, project_name
        );
        let worktree_path = host_repo.join(".pa").join("review").join(agent_id);

        let _ = Command::new("git")
            .args([
                "fetch",
                &vault_git_url,
                &format!("+refs/heads/pa/{0}/*:refs/remotes/pa/{0}/*", agent_id),
            ])
            .current_dir(host_repo)
            .output();

        if !worktree_path.exists() {
            if let Some(p) = worktree_path.parent() {
                let _ = fs::create_dir_all(p);
            }
            let _ = Command::new("git")
                .args([
                    "worktree",
                    "add",
                    worktree_path.to_str().unwrap_or(""),
                    &format!("pa/{}/task", agent_id),
                ])
                .current_dir(host_repo)
                .output();
        }

        Ok(worktree_path)
    }

    fn stop_factory(&self) -> Result<()> {
        let _ = Command::new("tart")
            .args(["stop", &self.vm_name])
            .output();
        Ok(())
    }

    fn get_status(&self) -> Result<serde_json::Value> {
        let rpc_res = self.execute_ssh_rpc("get_status", json!({}))?;
        let guest_data = rpc_res.get("result").cloned().unwrap_or(json!({}));
        Ok(json!({
            "backend": "macos-tart",
            "vm_name": self.vm_name,
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
    }
}
