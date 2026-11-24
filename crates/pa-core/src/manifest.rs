use anyhow::{bail, Context, Result};
use hmac::{Hmac, Mac};
use serde::{Deserialize, Serialize};
use sha2::Sha256;
use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};

use crate::schema::AgentSpec;

type HmacSha256 = Hmac<Sha256>;

pub fn generate_session_nonce() -> [u8; 32] {
    use sha2::Digest;
    let mut hasher = Sha256::new();
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0);
    let pid = std::process::id();
    hasher.update(now.to_le_bytes());
    hasher.update(pid.to_le_bytes());
    let res = hasher.finalize();
    let mut nonce = [0u8; 32];
    nonce.copy_from_slice(&res[..32]);
    nonce
}

pub fn derive_placeholder_token(session_nonce: &[u8], agent_id: &str, env_var: &str) -> String {
    let mut mac = HmacSha256::new_from_slice(session_nonce).expect("HMAC accepts keys of any size");
    mac.update(agent_id.as_bytes());
    mac.update(b":");
    mac.update(env_var.as_bytes());
    let digest = mac.finalize().into_bytes();
    let hex: String = digest.iter().map(|b| format!("{b:02x}")).collect();
    let prefix = if hex.len() >= 16 { &hex[..16] } else { &hex };
    format!("pa-tok-{agent_id}-{prefix}")
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct CapabilityHeader {
    pub name: String,
    #[serde(default)]
    pub category: String,
    #[serde(default = "default_version")]
    pub version: String,
    #[serde(default)]
    pub description: String,
    #[serde(default)]
    pub requires: Vec<String>,
}

fn default_version() -> String {
    "1.0.0".to_string()
}

#[derive(Debug, Clone, Serialize, Deserialize, Default, PartialEq)]
pub struct EntitlementsSpec {
    #[serde(default)]
    pub read_paths: Vec<String>,
    #[serde(default)]
    pub write_paths: Vec<String>,
    #[serde(default)]
    pub allow_gpu: bool,
    #[serde(default)]
    pub allow_network_bind: Vec<u16>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default, PartialEq)]
pub struct StagingSpec {
    #[serde(default)]
    pub install_prefix: String,
    #[serde(default)]
    pub bin_dirs: Vec<String>,
    #[serde(default)]
    pub fedora_packages: Vec<String>,
    #[serde(default)]
    pub macos_brew_packages: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default, PartialEq)]
pub struct TokenRuleSpec {
    pub env_var: String,
    #[serde(default)]
    pub keyring_service: Option<String>,
    #[serde(default)]
    pub keyring_key: Option<String>,
    #[serde(default)]
    pub allowed_hosts: Vec<String>,
}

impl TokenRuleSpec {
    pub fn resolve_secret(&self) -> Option<zeroize::Zeroizing<String>> {
        let key = self.keyring_key.as_deref().unwrap_or(&self.env_var);

        // 1. Direct environment variable lookup takes precedence (zero-prompt)
        if let Ok(val) = std::env::var(key) {
            if !val.is_empty() {
                return Some(zeroize::Zeroizing::new(val));
            }
        }
        if let Ok(val) = std::env::var(&self.env_var) {
            if !val.is_empty() {
                return Some(zeroize::Zeroizing::new(val));
            }
        }

        // 2. Check if running under automated test / CI / bypass mode
        let test_mode = cfg!(test)
            || std::env::var("PA_TEST_MODE")
                .map(|v| v == "1" || v.eq_ignore_ascii_case("true"))
                .unwrap_or(false)
            || std::env::var("PA_DISABLE_KEYRING")
                .map(|v| v == "1" || v.eq_ignore_ascii_case("true"))
                .unwrap_or(false)
            || std::env::var("CI").is_ok();

        if test_mode {
            return Some(zeroize::Zeroizing::new(format!(
                "pa-test-mock-secret-{}",
                key
            )));
        }

        // 3. Host OS keyring fallback
        let service = self.keyring_service.as_deref().unwrap_or("pa-container");
        if let Ok(entry) = keyring::Entry::new(service, key) {
            if let Ok(pwd) = entry.get_password() {
                if !pwd.is_empty() {
                    return Some(zeroize::Zeroizing::new(pwd));
                }
            }
        }

        None
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, Default, PartialEq)]
pub struct ProxySpec {
    #[serde(default)]
    pub allowlist: Vec<String>,
    #[serde(default)]
    pub tokens: Vec<TokenRuleSpec>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct CapabilityManifest {
    #[serde(default = "default_schema_version")]
    pub schema_version: String,
    pub capability: CapabilityHeader,
    #[serde(default)]
    pub staging: StagingSpec,
    #[serde(default)]
    pub entitlements: EntitlementsSpec,
    #[serde(default)]
    pub env: HashMap<String, String>,
    #[serde(default)]
    pub proxy: ProxySpec,
    #[serde(skip)]
    pub package_dir: PathBuf,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
pub struct ResolvedCapabilities {
    pub fedora_packages: Vec<String>,
    pub macos_brew_packages: Vec<String>,
    pub env: HashMap<String, String>,
    pub bin_dirs: Vec<PathBuf>,
    pub read_paths: Vec<String>,
    pub write_paths: Vec<String>,
    pub allow_gpu: bool,
    pub allowlist: Vec<String>,
    pub tokens: Vec<TokenRuleSpec>,
}

fn default_schema_version() -> String {
    "1.0".to_string()
}

#[derive(Default, Debug)]
pub struct CapabilityRegistry {
    by_name: HashMap<String, CapabilityManifest>,
}

impl CapabilityRegistry {
    pub fn discover(packages_root: &Path) -> Result<Self> {
        let mut by_name = HashMap::new();
        if !packages_root.exists() {
            return Ok(Self { by_name });
        }

        let mut visit_dirs = vec![packages_root.to_path_buf()];
        for sub in ["capabilities", "toolchains", "agents"] {
            let p = packages_root.join(sub);
            if p.is_dir() {
                visit_dirs.push(p);
            }
        }

        for dir in visit_dirs {
            if let Ok(entries) = fs::read_dir(&dir) {
                for entry in entries.flatten() {
                    let toml_path = entry.path().join("capability.toml");
                    if toml_path.is_file() {
                        let raw = fs::read_to_string(&toml_path)
                            .with_context(|| format!("Failed to read {}", toml_path.display()))?;
                        let mut manifest: CapabilityManifest =
                            toml::from_str(&raw).with_context(|| {
                                format!("Invalid capability.toml at {}", toml_path.display())
                            })?;
                        manifest.package_dir = entry.path();
                        by_name.insert(manifest.capability.name.clone(), manifest);
                    }
                }
            }
        }

        Ok(Self { by_name })
    }

    pub fn get(&self, name: &str) -> Option<&CapabilityManifest> {
        self.by_name.get(name)
    }

    pub fn len(&self) -> usize {
        self.by_name.len()
    }

    pub fn is_empty(&self) -> bool {
        self.by_name.is_empty()
    }

    pub fn resolve_dependency_closure(
        &self,
        requested: &[String],
    ) -> Result<Vec<CapabilityManifest>> {
        #[derive(Clone, Copy, PartialEq, Eq)]
        enum VisitState {
            Temp,
            Perm,
        }

        let mut state: HashMap<String, VisitState> = HashMap::new();
        let mut ordered = Vec::new();

        fn visit(
            reg: &CapabilityRegistry,
            name: &str,
            state: &mut HashMap<String, VisitState>,
            ordered: &mut Vec<CapabilityManifest>,
        ) -> Result<()> {
            match state.get(name) {
                Some(VisitState::Perm) => return Ok(()),
                Some(VisitState::Temp) => {
                    bail!("Circular capability dependency involving '{name}'")
                }
                None => {}
            }
            state.insert(name.to_string(), VisitState::Temp);
            let manifest = reg
                .by_name
                .get(name)
                .ok_or_else(|| anyhow::anyhow!("Unknown capability pack: '{}'", name))?;
            for dep in &manifest.capability.requires {
                visit(reg, dep, state, ordered)?;
            }
            state.insert(name.to_string(), VisitState::Perm);
            ordered.push(manifest.clone());
            Ok(())
        }

        for req in requested {
            visit(self, req, &mut state, &mut ordered)?;
        }

        Ok(ordered)
    }

    pub fn resolve_for_agent(&self, requested: &[String]) -> Result<ResolvedCapabilities> {
        let manifests = self.resolve_dependency_closure(requested)?;
        let mut resolved = ResolvedCapabilities::default();
        let mut seen_fedora = std::collections::HashSet::new();
        let mut seen_brew = std::collections::HashSet::new();
        let mut seen_allowlist = std::collections::HashSet::new();

        for m in manifests {
            for pkg in &m.staging.fedora_packages {
                if seen_fedora.insert(pkg.clone()) {
                    resolved.fedora_packages.push(pkg.clone());
                }
            }
            for pkg in &m.staging.macos_brew_packages {
                if seen_brew.insert(pkg.clone()) {
                    resolved.macos_brew_packages.push(pkg.clone());
                }
            }
            for (k, v) in &m.env {
                resolved.env.insert(k.clone(), v.clone());
            }
            for b in &m.staging.bin_dirs {
                let full_bin = if !m.staging.install_prefix.is_empty() {
                    PathBuf::from(&m.staging.install_prefix).join(b)
                } else {
                    m.package_dir.join(b)
                };
                resolved.bin_dirs.push(full_bin);
            }
            for p in &m.entitlements.read_paths {
                if !resolved.read_paths.contains(p) {
                    resolved.read_paths.push(p.clone());
                }
            }
            for p in &m.entitlements.write_paths {
                if !resolved.write_paths.contains(p) {
                    resolved.write_paths.push(p.clone());
                }
            }
            if m.entitlements.allow_gpu {
                resolved.allow_gpu = true;
            }
            for host in &m.proxy.allowlist {
                if seen_allowlist.insert(host.clone()) {
                    resolved.allowlist.push(host.clone());
                }
            }
            for tok in &m.proxy.tokens {
                resolved.tokens.push(tok.clone());
            }
        }

        Ok(resolved)
    }
}

pub fn merge_agent_capabilities(
    agents: &mut [AgentSpec],
    registry: &CapabilityRegistry,
) -> Result<()> {
    for agent in agents {
        if !agent.capabilities.is_empty() {
            let caps = registry.resolve_for_agent(&agent.capabilities)?;
            for host in caps.allowlist {
                if !agent.allowlist.contains(&host) {
                    agent.allowlist.push(host);
                }
            }
            for tok in caps.tokens {
                if !agent.tokens.contains(&tok.env_var) {
                    agent.tokens.push(tok.env_var);
                }
            }
        }
    }
    Ok(())
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct AcpServerBinding {
    pub name: String,
    pub service: String,
    pub command: PathBuf,
    pub args: Vec<String>,
}

impl AcpServerBinding {
    pub fn to_mcp_entry_json(&self) -> serde_json::Value {
        serde_json::json!({
            "command": self.command.to_string_lossy(),
            "args": self.args
        })
    }

    pub fn to_opencode_entry_json(&self) -> serde_json::Value {
        let mut cmd = vec![self.command.to_string_lossy().to_string()];
        cmd.extend(self.args.clone());
        serde_json::json!({
            "type": "local",
            "command": cmd,
            "enabled": true
        })
    }
}

pub fn resolve_role_acp_bindings(
    acp_services: &[String],
    packages_root: &Path,
) -> Vec<AcpServerBinding> {
    let mut bindings = Vec::new();
    for entry in acp_services {
        let parts: Vec<&str> = entry.split(':').collect();
        let name = parts[0];
        let service = if parts.len() > 1 { parts[1] } else { "read" };

        let candidate_dirs = [
            packages_root.join("capabilities").join(name),
            packages_root.join(name),
        ];

        for dir in candidate_dirs {
            let mcp_server = dir.join("mcp").join("server.py");
            let short_name = name.strip_suffix("_acp").unwrap_or(name);
            let bin_wrapper = dir.join("bin").join(format!("pa-{}-mcp", short_name));
            let bin_wrapper_alt = dir
                .join("bin")
                .join(format!("pa-{}-mcp", short_name.replace('_', "-")));
            let bin_wrapper_prefix = if let Some((prefix, _)) = short_name.split_once('_') {
                dir.join("bin").join(format!("pa-{prefix}-mcp"))
            } else {
                bin_wrapper.clone()
            };

            let target_bin = if mcp_server.is_file() {
                Some(mcp_server)
            } else if bin_wrapper.is_file() {
                Some(bin_wrapper)
            } else if bin_wrapper_alt.is_file() {
                Some(bin_wrapper_alt)
            } else if bin_wrapper_prefix.is_file() {
                Some(bin_wrapper_prefix)
            } else {
                None
            };

            if let Some(cmd) = target_bin {
                bindings.push(AcpServerBinding {
                    name: name.to_string(),
                    service: service.to_string(),
                    command: cmd,
                    args: vec![],
                });
                break;
            }
        }
    }
    bindings
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_derive_placeholder_token() {
        let nonce = b"test_session_nonce_1234567890";
        let tok1 = derive_placeholder_token(nonce, "agent1", "OPENAI_API_KEY");
        let tok2 = derive_placeholder_token(nonce, "agent1", "OPENAI_API_KEY");
        let tok3 = derive_placeholder_token(nonce, "agent2", "OPENAI_API_KEY");
        assert_eq!(tok1, tok2);
        assert_ne!(tok1, tok3);
        assert!(tok1.starts_with("pa-tok-agent1-"));
    }

    #[test]
    fn test_discover_and_resolve_capabilities() {
        let packages_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../..")
            .join("pa_packages");
        let reg = CapabilityRegistry::discover(&packages_dir).unwrap();
        assert_eq!(reg.len(), 21);
        assert!(reg.get("git").is_some());
        assert!(reg.get("source-control").is_some());
        assert!(reg.get("telemetry_acp").is_some());
        assert!(reg.get("design_system_acp").is_some());

        let resolved = reg
            .resolve_dependency_closure(&["source-control".to_string()])
            .unwrap();
        assert_eq!(resolved.len(), 2);
        assert_eq!(resolved[0].capability.name, "git");
        assert_eq!(resolved[1].capability.name, "source-control");

        let agent_caps = reg
            .resolve_for_agent(&["source-control".to_string()])
            .unwrap();
        assert!(!agent_caps.allowlist.is_empty());

        let mut agents = vec![AgentSpec {
            id: "agent1".into(),
            driver: "pi".into(),
            role: None,
            uid: 2001,
            socket_path: None,
            capabilities: vec!["source-control".into()],
            allowlist: vec!["custom.domain".into()],
            tokens: vec!["CUSTOM_TOKEN".into()],
            proxy_port: None,
            transparent_port: None,
            branch_prefix: "pa/agent1".into(),
        }];
        merge_agent_capabilities(&mut agents, &reg).unwrap();
        assert!(agents[0].allowlist.contains(&"custom.domain".to_string()));
        assert!(agents[0].allowlist.contains(&"github.com".to_string()));
        assert!(agents[0].tokens.contains(&"CUSTOM_TOKEN".to_string()));
        assert!(agents[0].tokens.contains(&"GITHUB_TOKEN".to_string()));
    }

    #[test]
    fn test_resolve_secret_env_override() {
        std::env::set_var("TEST_CUSTOM_SECRET_KEY", "my-env-secret-value");
        let rule = TokenRuleSpec {
            env_var: "TEST_CUSTOM_SECRET_KEY".to_string(),
            keyring_service: Some("pa-container".to_string()),
            keyring_key: Some("TEST_CUSTOM_SECRET_KEY".to_string()),
            allowed_hosts: vec![],
        };
        let secret = rule.resolve_secret().expect("Should resolve from env");
        assert_eq!(*secret, "my-env-secret-value");
        std::env::remove_var("TEST_CUSTOM_SECRET_KEY");
    }

    #[test]
    fn test_resolve_secret_test_mode_synthetic() {
        std::env::set_var("PA_DISABLE_KEYRING", "1");
        let rule = TokenRuleSpec {
            env_var: "NON_EXISTENT_KEYRING_KEY_123".to_string(),
            keyring_service: Some("pa-container".to_string()),
            keyring_key: Some("NON_EXISTENT_KEYRING_KEY_123".to_string()),
            allowed_hosts: vec![],
        };
        let secret = rule
            .resolve_secret()
            .expect("Should resolve synthetic secret in test mode");
        assert_eq!(*secret, "pa-test-mock-secret-NON_EXISTENT_KEYRING_KEY_123");
        std::env::remove_var("PA_DISABLE_KEYRING");
    }

    #[test]
    fn test_resolve_role_acp_bindings() {
        let packages_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../..")
            .join("pa_packages");
        let bindings = resolve_role_acp_bindings(
            &[
                "telemetry_acp:read".to_string(),
                "design_system_acp:read".to_string(),
            ],
            &packages_dir,
        );
        assert_eq!(bindings.len(), 2);
        assert_eq!(bindings[0].name, "telemetry_acp");
        assert_eq!(bindings[0].service, "read");
        assert!(bindings[0].command.is_file());
        assert_eq!(bindings[1].name, "design_system_acp");
        assert_eq!(bindings[1].service, "read");
        assert!(bindings[1].command.is_file());

        let mcp_json = bindings[0].to_mcp_entry_json();
        assert!(mcp_json.get("command").is_some());
        assert!(mcp_json.get("args").is_some());
    }
}
