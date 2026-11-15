use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct FactoryMetadata {
    #[serde(default = "default_factory_name")]
    pub name: String,
    #[serde(default)]
    pub description: String,
}

fn default_factory_name() -> String {
    "default-factory".to_string()
}

impl Default for FactoryMetadata {
    fn default() -> Self {
        Self {
            name: default_factory_name(),
            description: String::new(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct MetalSpec {
    #[serde(default)]
    pub enabled: bool,
    #[serde(default = "default_metal_host_mode")]
    pub host_mode: String,
    #[serde(default = "default_apple_family_max")]
    pub apple_family_max: u32,
    #[serde(default = "default_max_threadgroup_memory")]
    pub max_threadgroup_memory: u64,
}

fn default_metal_host_mode() -> String {
    "ephemeral".to_string()
}

fn default_apple_family_max() -> u32 {
    1009
}

fn default_max_threadgroup_memory() -> u64 {
    65536
}

impl Default for MetalSpec {
    fn default() -> Self {
        Self {
            enabled: false,
            host_mode: default_metal_host_mode(),
            apple_family_max: default_apple_family_max(),
            max_threadgroup_memory: default_max_threadgroup_memory(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ComputeSpec {
    #[serde(default = "default_backend")]
    pub backend: String,
    #[serde(default = "default_cpus")]
    pub cpus: u32,
    #[serde(default = "default_memory")]
    pub memory_mb: u32,
    #[serde(default = "default_gpu")]
    pub gpu: String,
    #[serde(default)]
    pub metal: MetalSpec,
}

fn default_backend() -> String {
    "auto".to_string()
}
fn default_cpus() -> u32 {
    8
}
fn default_memory() -> u32 {
    16384
}
fn default_gpu() -> String {
    "optional".to_string()
}

impl Default for ComputeSpec {
    fn default() -> Self {
        Self {
            backend: default_backend(),
            cpus: default_cpus(),
            memory_mb: default_memory(),
            gpu: default_gpu(),
            metal: MetalSpec::default(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, Default, PartialEq)]
pub struct CapabilitiesSpec {
    #[serde(default)]
    pub installed: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct LlamaServerSpec {
    #[serde(default)]
    pub enabled: bool,
    #[serde(default)]
    pub model: String,
    #[serde(default = "default_ctx_size")]
    pub ctx_size: u32,
    #[serde(default = "default_gpu_layers")]
    pub gpu_layers: String,
}

fn default_ctx_size() -> u32 {
    32768
}
fn default_gpu_layers() -> String {
    "all".to_string()
}

impl Default for LlamaServerSpec {
    fn default() -> Self {
        Self {
            enabled: false,
            model: String::new(),
            ctx_size: default_ctx_size(),
            gpu_layers: default_gpu_layers(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, Default, PartialEq)]
pub struct InferenceSpec {
    #[serde(default)]
    pub llama_server: LlamaServerSpec,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct UiSpec {
    #[serde(default)]
    pub t3_code: bool,
    #[serde(default = "default_virtual_desktop")]
    pub virtual_desktop: String,
}

fn default_virtual_desktop() -> String {
    "none".to_string()
}

impl Default for UiSpec {
    fn default() -> Self {
        Self {
            t3_code: false,
            virtual_desktop: default_virtual_desktop(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct AgentSpec {
    pub id: String,
    #[serde(default = "default_driver")]
    pub driver: String,
    #[serde(default = "default_uid")]
    pub uid: u32,
    #[serde(default)]
    pub socket_path: Option<PathBuf>,
    #[serde(default)]
    pub proxy_port: Option<u16>,
    #[serde(default)]
    pub transparent_port: Option<u16>,
    #[serde(default = "default_branch_prefix")]
    pub branch_prefix: String,
    #[serde(default)]
    pub capabilities: Vec<String>,
    #[serde(default)]
    pub allowlist: Vec<String>,
    #[serde(default)]
    pub tokens: Vec<String>,
}

fn default_driver() -> String {
    "pi".to_string()
}
fn default_uid() -> u32 {
    2001
}
fn default_branch_prefix() -> String {
    "pa".to_string()
}

impl AgentSpec {
    pub fn new(id: impl Into<String>) -> Self {
        let id_str = id.into();
        Self {
            id: id_str.clone(),
            driver: default_driver(),
            uid: default_uid(),
            socket_path: None,
            proxy_port: None,
            transparent_port: None,
            branch_prefix: format!("pa/{}", id_str),
            capabilities: Vec::new(),
            allowlist: Vec::new(),
            tokens: Vec::new(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct FactoryConfig {
    #[serde(default = "default_schema_version")]
    pub schema_version: String,
    #[serde(default)]
    pub factory: FactoryMetadata,
    #[serde(default)]
    pub compute: ComputeSpec,
    #[serde(default)]
    pub capabilities: CapabilitiesSpec,
    #[serde(default)]
    pub inference: InferenceSpec,
    #[serde(default)]
    pub ui: UiSpec,
    #[serde(default)]
    pub agents: Vec<AgentSpec>,
}

fn default_schema_version() -> String {
    "2.0".to_string()
}

impl Default for FactoryConfig {
    fn default() -> Self {
        Self {
            schema_version: default_schema_version(),
            factory: FactoryMetadata::default(),
            compute: ComputeSpec::default(),
            capabilities: CapabilitiesSpec::default(),
            inference: InferenceSpec::default(),
            ui: UiSpec::default(),
            agents: vec![AgentSpec::new("agent1")],
        }
    }
}

pub fn resolve_agent_sockets(agents: &[AgentSpec], sockets_dir: &Path) -> Vec<AgentSpec> {
    agents
        .iter()
        .map(|a| {
            let sock = a
                .socket_path
                .clone()
                .unwrap_or_else(|| sockets_dir.join(format!("{}.sock", a.id)));
            let mut updated = a.clone();
            updated.socket_path = Some(sock);
            updated
        })
        .collect()
}

pub fn load_factory_config(path: Option<&Path>) -> Result<FactoryConfig> {
    let target = match path {
        Some(p) => Some(p.to_path_buf()),
        None => {
            let direct = PathBuf::from("factory.toml");
            let nested = PathBuf::from(".pa-container/factory.toml");
            if direct.is_file() {
                Some(direct)
            } else if nested.is_file() {
                Some(nested)
            } else {
                None
            }
        }
    };

    match target {
        Some(p) if p.is_file() => {
            let content = std::fs::read_to_string(&p)
                .with_context(|| format!("Failed to read {}", p.display()))?;
            let mut cfg: FactoryConfig = toml::from_str(&content)
                .with_context(|| format!("Failed to parse {}", p.display()))?;
            if cfg.agents.is_empty() {
                cfg.agents.push(AgentSpec::new("agent1"));
            }
            Ok(cfg)
        }
        _ => Ok(FactoryConfig::default()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_resolve_agent_sockets() {
        let base_dir = Path::new("/run/pa-container/sockets");
        let agents = vec![
            AgentSpec::new("lead-architect"),
            AgentSpec {
                socket_path: Some(PathBuf::from("/custom/special.sock")),
                ..AgentSpec::new("custom-worker")
            },
        ];

        let resolved = resolve_agent_sockets(&agents, base_dir);
        assert_eq!(resolved.len(), 2);
        assert_eq!(
            resolved[0].socket_path,
            Some(PathBuf::from(
                "/run/pa-container/sockets/lead-architect.sock"
            ))
        );
        assert_eq!(
            resolved[1].socket_path,
            Some(PathBuf::from("/custom/special.sock"))
        );
    }

    #[test]
    fn test_metal_spec_defaults() {
        let default_metal = MetalSpec::default();
        assert!(!default_metal.enabled);
        assert_eq!(default_metal.host_mode, "ephemeral");
        assert_eq!(default_metal.apple_family_max, 1009);
        assert_eq!(default_metal.max_threadgroup_memory, 65536);

        let default_compute = ComputeSpec::default();
        assert!(!default_compute.metal.enabled);
        assert_eq!(default_compute.metal.host_mode, "ephemeral");
    }

    #[test]
    fn test_metal_spec_toml_deserialization() {
        let toml_str = r#"
schema_version = "2.0"

[compute]
backend = "macos-tart"
cpus = 6
memory_mb = 12288
gpu = "required"

[compute.metal]
enabled = true
host_mode = "persistent"
apple_family_max = 1008
max_threadgroup_memory = 32768
"#;
        let config: FactoryConfig = toml::from_str(toml_str).expect("Failed to parse TOML");
        assert_eq!(config.compute.backend, "macos-tart");
        assert_eq!(config.compute.cpus, 6);
        assert_eq!(config.compute.gpu, "required");
        assert!(config.compute.metal.enabled);
        assert_eq!(config.compute.metal.host_mode, "persistent");
        assert_eq!(config.compute.metal.apple_family_max, 1008);
        assert_eq!(config.compute.metal.max_threadgroup_memory, 32768);
    }
}
