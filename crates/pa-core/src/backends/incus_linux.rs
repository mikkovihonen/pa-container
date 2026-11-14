use anyhow::{Context, Result};
use serde_json::json;
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

use crate::backend::FactoryBackend;
use crate::schema::{resolve_agent_ports, AgentSpec, FactoryConfig};

pub const DEFAULT_BRIDGE_IP: &str = "10.240.0.1";
pub const DEFAULT_VM_NAME: &str = "pa-factory-linux";

pub struct IncusLinuxBackend {
    pub config: Option<FactoryConfig>,
    pub vm_name: String,
    pub bridge_ip: String,
    pub ssh_user: String,
    pub ssh_port: u16,
    pub project_name: std::sync::Mutex<String>,
}

impl IncusLinuxBackend {
    pub fn new(
        config: Option<FactoryConfig>,
        vm_name: Option<String>,
        bridge_ip: Option<String>,
        ssh_user: Option<String>,
        ssh_port: Option<u16>,
    ) -> Self {
        Self {
            config,
            vm_name: vm_name.unwrap_or_else(|| DEFAULT_VM_NAME.to_string()),
            bridge_ip: bridge_ip.unwrap_or_else(|| DEFAULT_BRIDGE_IP.to_string()),
            ssh_user: ssh_user.unwrap_or_else(|| "admin".to_string()),
            ssh_port: ssh_port.unwrap_or(2222),
            project_name: std::sync::Mutex::new("project".to_string()),
        }
    }

    pub fn get_vm_ip(&self) -> Result<String> {
        let out = Command::new("incus")
            .args(["list", &self.vm_name, "--format", "json"])
            .output()
            .with_context(|| format!("Failed to run incus list for '{}'", self.vm_name))?;

        if !out.status.success() {
            anyhow::bail!(
                "Incus VM '{}' list failed: {}",
                self.vm_name,
                String::from_utf8_lossy(&out.stderr)
            );
        }

        let instances: serde_json::Value = serde_json::from_slice(&out.stdout)
            .context("Failed to parse incus list JSON output")?;

        if let Some(arr) = instances.as_array() {
            if let Some(vm) = arr.first() {
                if let Some(net) = vm.pointer("/state/network/eth0/addresses") {
                    if let Some(addrs) = net.as_array() {
                        for a in addrs {
                            if a.get("family").and_then(|f| f.as_str()) == Some("inet") {
                                if let Some(ip) = a.get("address").and_then(|s| s.as_str()) {
                                    return Ok(ip.to_string());
                                }
                            }
                        }
                    }
                }
            }
        }

        anyhow::bail!(
            "Incus VM '{}' has not acquired an active IPv4 address",
            self.vm_name
        )
    }

    pub fn execute_ssh_rpc(
        &self,
        method: &str,
        params: serde_json::Value,
    ) -> Result<serde_json::Value> {
        let vm_ip = self.get_vm_ip()?;
        let payload = json!({
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params,
        });
        let payload_str = serde_json::to_string(&payload)?;

        let mut child = Command::new("ssh")
            .args([
                "-p",
                &self.ssh_port.to_string(),
                "-o",
                "StrictHostKeyChecking=no",
                "-o",
                "UserKnownHostsFile=/dev/null",
                "-o",
                "ConnectTimeout=5",
                &format!("{}@{}", self.ssh_user, vm_ip),
                "pa-agentd",
                "--stdio",
            ])
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

impl FactoryBackend for IncusLinuxBackend {
    fn start_proxy(&self, config: &FactoryConfig) -> Result<String> {
        let agents = resolve_agent_ports(&config.agents, false);
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

            proxy_rules.push(json!({
                "id": a.id,
                "agent_id": a.id,
                "user": a.id,
                "driver": a.driver,
                "proxy_port": a.proxy_port,
                "transparent_port": a.transparent_port,
                "allowed_hosts": a.allowlist,
                "token_placeholders": placeholders,
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

        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let _ = fs::set_permissions(&proxy_config_path, fs::Permissions::from_mode(0o600));
        }

        let _ = crate::backend::ensure_proxy_server(&self.bridge_ip, &proxy_config_path, &agents);

        Ok(self.bridge_ip.clone())
    }

    fn ensure_factory_vm(&self, config: &FactoryConfig, _proxy_ip: &str) -> Result<()> {
        let check = Command::new("incus").args(["info", &self.vm_name]).output();

        if check.is_err() || !check.unwrap().status.success() {
            let launch_status = Command::new("incus")
                .args([
                    "launch",
                    "images:fedora/41/cloud",
                    &self.vm_name,
                    "--vm",
                    "-c",
                    &format!("limits.cpu={}", config.compute.cpus),
                    "-c",
                    &format!("limits.memory={}MB", config.compute.memory_mb),
                ])
                .status()
                .with_context(|| format!("Failed to launch Incus VM '{}'", self.vm_name))?;

            if !launch_status.success() {
                anyhow::bail!("incus launch failed for VM '{}'", self.vm_name);
            }

            if config.compute.gpu == "optional" || config.compute.gpu == "required" {
                let _ = Command::new("incus")
                    .args(["config", "device", "add", &self.vm_name, "gpu", "gpu"])
                    .output();
            }
        }

        Ok(())
    }

    fn sync_git_to_vault(&self, host_repo: &Path, branch: &str) -> Result<String> {
        let project_name = host_repo
            .file_name()
            .and_then(|s| s.to_str())
            .unwrap_or("project");

        *self.project_name.lock().unwrap() = project_name.to_string();

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

        let out = Command::new("git")
            .args([
                "push",
                "-f",
                &vault_git_url,
                &format!("{}:refs/heads/main", commit_to_push),
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
            anyhow::bail!(
                "Package provisioning failed on Linux Incus guest: {:?}",
                res
            );
        }
    }

    fn provision_capabilities(&self, caps: &crate::manifest::ResolvedCapabilities) -> Result<()> {
        self.provision_packages(&caps.fedora_packages)
    }

    fn launch_agent(
        &self,
        agent: &AgentSpec,
        task_prompt: Option<&str>,
        capabilities: Option<&crate::manifest::ResolvedCapabilities>,
    ) -> Result<i32> {
        self.execute_ssh_rpc(
            "provision_user",
            json!({
                "username": agent.id,
                "uid": agent.uid,
            }),
        )?;

        let agents_data = vec![json!({
            "id": agent.id,
            "user": agent.id,
            "proxy_port": agent.proxy_port.unwrap_or(8081),
            "transparent_port": agent.transparent_port.unwrap_or(8091),
        })];

        self.execute_ssh_rpc(
            "update_firewall",
            json!({
                "proxy_ip": self.bridge_ip,
                "dns_port": 5353,
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
            "proxy_ip": self.bridge_ip,
            "proxy_port": agent.proxy_port.unwrap_or(8081),
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

        let res = self.execute_ssh_rpc("launch_agent", payload)?;

        if res.get("result").is_some() {
            Ok(0)
        } else {
            anyhow::bail!("Failed to launch agent '{}': {:?}", agent.id, res);
        }
    }

    fn fetch_agent_branch(&self, agent_id: &str, host_repo: &Path) -> Result<PathBuf> {
        let project_name = self.project_name.lock().unwrap().clone();

        let vm_ip = self.get_vm_ip()?;
        let vault_git_url = format!(
            "ssh://{}@{}:{}/var/pa-vault/{}.git",
            self.ssh_user, vm_ip, self.ssh_port, project_name
        );
        let worktree_path = host_repo.join(".pa").join("review").join(agent_id);

        let out = Command::new("git")
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

        if !worktree_path.exists() {
            if let Some(p) = worktree_path.parent() {
                let _ = fs::create_dir_all(p);
            }
            let add_out = Command::new("git")
                .args([
                    "worktree",
                    "add",
                    worktree_path.to_str().unwrap_or(""),
                    &format!("pa/{}/task", agent_id),
                ])
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
        let status = Command::new("incus")
            .args(["stop", &self.vm_name])
            .status()
            .with_context(|| format!("Failed to stop Incus VM '{}'", self.vm_name))?;

        if !status.success() {
            anyhow::bail!("incus stop failed for VM '{}'", self.vm_name);
        }
        Ok(())
    }

    fn get_status(&self) -> Result<serde_json::Value> {
        let rpc_res = self.execute_ssh_rpc("get_status", json!({}))?;
        let guest_data = rpc_res.get("result").cloned().unwrap_or(json!({}));
        Ok(json!({
            "backend": "linux-incus",
            "vm_name": self.vm_name,
            "bridge_ip": self.bridge_ip,
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
    fn test_incus_backend_defaults() {
        let backend = IncusLinuxBackend::new(None, None, None, None, None);
        assert_eq!(backend.vm_name, DEFAULT_VM_NAME);
        assert_eq!(backend.bridge_ip, DEFAULT_BRIDGE_IP);
    }

    #[test]
    fn test_incus_start_proxy() {
        let backend = IncusLinuxBackend::new(None, None, None, None, None);
        let cfg = FactoryConfig::default();
        let ip = backend.start_proxy(&cfg).unwrap();
        assert_eq!(ip, DEFAULT_BRIDGE_IP);
    }
}
