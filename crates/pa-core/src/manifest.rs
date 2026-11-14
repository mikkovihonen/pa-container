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
        let service = self.keyring_service.as_deref().unwrap_or("pa-container");
        let key = self.keyring_key.as_deref().unwrap_or(&self.env_var);

        if let Ok(entry) = keyring::Entry::new(service, key) {
            if let Ok(pwd) = entry.get_password() {
                if !pwd.is_empty() {
                    return Some(zeroize::Zeroizing::new(pwd));
                }
            }
        }

        if let Ok(val) = std::env::var(key) {
            if !val.is_empty() {
                return Some(zeroize::Zeroizing::new(val));
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
        assert_eq!(reg.len(), 23);
        assert!(reg.get("git").is_some());
        assert!(reg.get("source-control").is_some());

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
            uid: 2001,
            driver: "pi".into(),
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
}
