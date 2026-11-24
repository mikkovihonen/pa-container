use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
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
    #[serde(default)]
    pub role: Option<String>,
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
            role: None,
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

fn default_true() -> bool {
    true
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct OtlpTelemetrySpec {
    #[serde(default = "default_otlp_provider")]
    pub provider: String,
    #[serde(default = "default_otlp_endpoint")]
    pub endpoint: String,
    #[serde(default = "default_batch_timeout_ms")]
    pub batch_timeout_ms: u64,
    #[serde(default = "default_max_queue_size")]
    pub max_queue_size: usize,
    #[serde(default = "default_true")]
    pub scrub_secrets: bool,
    #[serde(default)]
    pub auth_keyring_key: Option<String>,
}

fn default_otlp_provider() -> String {
    "phoenix".to_string()
}
fn default_otlp_endpoint() -> String {
    "http://127.0.0.1:6006/v1/traces".to_string()
}
fn default_batch_timeout_ms() -> u64 {
    1000
}
fn default_max_queue_size() -> usize {
    2048
}

impl Default for OtlpTelemetrySpec {
    fn default() -> Self {
        Self {
            provider: default_otlp_provider(),
            endpoint: default_otlp_endpoint(),
            batch_timeout_ms: default_batch_timeout_ms(),
            max_queue_size: default_max_queue_size(),
            scrub_secrets: true,
            auth_keyring_key: None,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, Default, PartialEq)]
pub struct TelemetryConfig {
    #[serde(default)]
    pub otlp: OtlpTelemetrySpec,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct StorageConfig {
    #[serde(default = "default_storage_provider")]
    pub provider: String,
    #[serde(default = "default_storage_path")]
    pub path: PathBuf,
}

fn default_storage_provider() -> String {
    "sqlite".to_string()
}
fn default_storage_path() -> PathBuf {
    PathBuf::from(".pa/factory.db")
}

impl Default for StorageConfig {
    fn default() -> Self {
        Self {
            provider: default_storage_provider(),
            path: default_storage_path(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct TraceabilityConfig {
    #[serde(default = "default_traceability_engine")]
    pub engine: String,
    #[serde(default = "default_spec_dir")]
    pub spec_dir: PathBuf,
    #[serde(default = "default_min_coverage")]
    pub min_coverage_pct: f64,
    #[serde(default = "default_true")]
    pub enforce_test_linkage: bool,
    #[serde(default)]
    pub custom_cmd: Option<String>,
}

fn default_traceability_engine() -> String {
    "openfasttrace".to_string()
}
fn default_spec_dir() -> PathBuf {
    PathBuf::from("docs/specs")
}
fn default_min_coverage() -> f64 {
    95.0
}

impl Default for TraceabilityConfig {
    fn default() -> Self {
        Self {
            engine: default_traceability_engine(),
            spec_dir: default_spec_dir(),
            min_coverage_pct: default_min_coverage(),
            enforce_test_linkage: true,
            custom_cmd: None,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct WebPlatformSpec {
    #[serde(default = "default_web_catalog")]
    pub catalog: String,
    #[serde(default = "default_web_a11y")]
    pub a11y_engine: String,
    #[serde(default = "default_web_visual")]
    pub visual_regression: String,
}

fn default_web_catalog() -> String {
    "storybook".to_string()
}
fn default_web_a11y() -> String {
    "axe_core".to_string()
}
fn default_web_visual() -> String {
    "lost_pixel".to_string()
}

impl Default for WebPlatformSpec {
    fn default() -> Self {
        Self {
            catalog: default_web_catalog(),
            a11y_engine: default_web_a11y(),
            visual_regression: default_web_visual(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct IosPlatformSpec {
    #[serde(default = "default_ios_catalog")]
    pub catalog: String,
    #[serde(default = "default_ios_runner")]
    pub runner: String,
    #[serde(default = "default_ios_a11y")]
    pub a11y_engine: String,
    #[serde(default = "default_ios_visual")]
    pub visual_regression: String,
}

fn default_ios_catalog() -> String {
    "swiftui_previews".to_string()
}
fn default_ios_runner() -> String {
    "ios_runnerd".to_string()
}
fn default_ios_a11y() -> String {
    "xctest_a11y".to_string()
}
fn default_ios_visual() -> String {
    "swift_snapshot".to_string()
}

impl Default for IosPlatformSpec {
    fn default() -> Self {
        Self {
            catalog: default_ios_catalog(),
            runner: default_ios_runner(),
            a11y_engine: default_ios_a11y(),
            visual_regression: default_ios_visual(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct AndroidPlatformSpec {
    #[serde(default = "default_android_catalog")]
    pub catalog: String,
    #[serde(default = "default_android_runner")]
    pub runner: String,
    #[serde(default = "default_android_a11y")]
    pub a11y_engine: String,
    #[serde(default = "default_android_visual")]
    pub visual_regression: String,
}

fn default_android_catalog() -> String {
    "compose_previews".to_string()
}
fn default_android_runner() -> String {
    "adb_emulator".to_string()
}
fn default_android_a11y() -> String {
    "espresso_a11y".to_string()
}
fn default_android_visual() -> String {
    "paparazzi".to_string()
}

impl Default for AndroidPlatformSpec {
    fn default() -> Self {
        Self {
            catalog: default_android_catalog(),
            runner: default_android_runner(),
            a11y_engine: default_android_a11y(),
            visual_regression: default_android_visual(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct DesignSystemConfig {
    #[serde(default = "default_design_provider")]
    pub provider: String,
    #[serde(default = "default_tokens_path")]
    pub tokens_path: PathBuf,
    #[serde(default = "default_contracts_path")]
    pub contracts_path: PathBuf,
    #[serde(default = "default_design_platforms")]
    pub platforms: Vec<String>,
    #[serde(default = "default_on_missing_platform")]
    pub on_missing_platform: String,
    #[serde(default)]
    pub endpoint: Option<String>,
    #[serde(default)]
    pub auth_key: Option<String>,
    #[serde(default)]
    pub web: WebPlatformSpec,
    #[serde(default)]
    pub ios: IosPlatformSpec,
    #[serde(default)]
    pub android: AndroidPlatformSpec,
}

fn default_design_provider() -> String {
    "git_only".to_string()
}
fn default_tokens_path() -> PathBuf {
    PathBuf::from("design/tokens/tokens.json")
}
fn default_contracts_path() -> PathBuf {
    PathBuf::from("design/contracts")
}
fn default_design_platforms() -> Vec<String> {
    vec!["web".to_string()]
}
fn default_on_missing_platform() -> String {
    "fail".to_string()
}

impl Default for DesignSystemConfig {
    fn default() -> Self {
        Self {
            provider: default_design_provider(),
            tokens_path: default_tokens_path(),
            contracts_path: default_contracts_path(),
            platforms: default_design_platforms(),
            on_missing_platform: default_on_missing_platform(),
            endpoint: None,
            auth_key: None,
            web: WebPlatformSpec::default(),
            ios: IosPlatformSpec::default(),
            android: AndroidPlatformSpec::default(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct GovernanceConfig {
    #[serde(default = "default_max_wip_prs")]
    pub max_wip_prs: usize,
    #[serde(default = "default_slo_defense")]
    pub slo_defense_error_budget_min: f64,
    #[serde(default = "default_budget_usd")]
    pub budget_usd_per_kr: f64,
}

fn default_max_wip_prs() -> usize {
    5
}
fn default_slo_defense() -> f64 {
    0.99
}
fn default_budget_usd() -> f64 {
    50.0
}

impl Default for GovernanceConfig {
    fn default() -> Self {
        Self {
            max_wip_prs: default_max_wip_prs(),
            slo_defense_error_budget_min: default_slo_defense(),
            budget_usd_per_kr: default_budget_usd(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct RoleSpec {
    #[serde(default = "default_driver")]
    pub driver: String,
    #[serde(default = "default_model_tier")]
    pub model_tier: String,
    #[serde(default)]
    pub capabilities: Vec<String>,
    #[serde(default)]
    pub env: HashMap<String, String>,
}

fn default_model_tier() -> String {
    "frontier".to_string()
}

impl Default for RoleSpec {
    fn default() -> Self {
        Self {
            driver: default_driver(),
            model_tier: default_model_tier(),
            capabilities: Vec::new(),
            env: HashMap::new(),
        }
    }
}

pub fn default_factory_roles() -> HashMap<String, RoleSpec> {
    let mut roles = HashMap::new();
    roles.insert(
        "spec_architect".to_string(),
        RoleSpec {
            driver: "antigravity".to_string(),
            model_tier: "frontier".to_string(),
            capabilities: vec!["git".to_string(), "source-control".to_string()],
            env: HashMap::new(),
        },
    );
    roles.insert(
        "design_engineer".to_string(),
        RoleSpec {
            driver: "claude".to_string(),
            model_tier: "frontier".to_string(),
            capabilities: vec![
                "git".to_string(),
                "browser".to_string(),
                "virtual-desktop".to_string(),
                "ios-simulator".to_string(),
            ],
            env: HashMap::new(),
        },
    );
    roles.insert(
        "design_steward".to_string(),
        RoleSpec {
            driver: "pi".to_string(),
            model_tier: "local".to_string(),
            capabilities: vec!["git".to_string(), "source-control".to_string()],
            env: HashMap::new(),
        },
    );
    roles.insert(
        "traceability_auditor".to_string(),
        RoleSpec {
            driver: "pi".to_string(),
            model_tier: "local".to_string(),
            capabilities: vec!["git".to_string(), "source-control".to_string()],
            env: HashMap::new(),
        },
    );
    roles.insert(
        "factory_diagnostician".to_string(),
        RoleSpec {
            driver: "antigravity".to_string(),
            model_tier: "frontier".to_string(),
            capabilities: vec!["git".to_string(), "source-control".to_string()],
            env: HashMap::new(),
        },
    );
    roles.insert(
        "okr_analyst".to_string(),
        RoleSpec {
            driver: "pi".to_string(),
            model_tier: "local".to_string(),
            capabilities: vec!["git".to_string()],
            env: HashMap::new(),
        },
    );
    roles
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
    #[serde(default)]
    pub telemetry: TelemetryConfig,
    #[serde(default)]
    pub storage: StorageConfig,
    #[serde(default)]
    pub traceability: TraceabilityConfig,
    #[serde(default)]
    pub design_system: DesignSystemConfig,
    #[serde(default)]
    pub governance: GovernanceConfig,
    #[serde(default = "default_factory_roles")]
    pub roles: HashMap<String, RoleSpec>,
}

fn default_schema_version() -> String {
    "2.1".to_string()
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
            telemetry: TelemetryConfig::default(),
            storage: StorageConfig::default(),
            traceability: TraceabilityConfig::default(),
            design_system: DesignSystemConfig::default(),
            governance: GovernanceConfig::default(),
            roles: default_factory_roles(),
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

    #[test]
    fn test_factory_config_extended_defaults() {
        let config = FactoryConfig::default();
        assert_eq!(config.telemetry.otlp.provider, "phoenix");
        assert_eq!(
            config.telemetry.otlp.endpoint,
            "http://127.0.0.1:6006/v1/traces"
        );
        assert!(config.telemetry.otlp.scrub_secrets);
        assert_eq!(config.storage.provider, "sqlite");
        assert_eq!(config.storage.path, PathBuf::from(".pa/factory.db"));
        assert_eq!(config.traceability.engine, "openfasttrace");
        assert_eq!(config.traceability.min_coverage_pct, 95.0);
        assert_eq!(config.design_system.provider, "git_only");
        assert_eq!(config.design_system.platforms, vec!["web"]);
        assert_eq!(config.design_system.on_missing_platform, "fail");
        assert_eq!(config.design_system.web.a11y_engine, "axe_core");
        assert_eq!(config.design_system.ios.runner, "ios_runnerd");
        assert_eq!(config.design_system.android.runner, "adb_emulator");
        assert_eq!(config.governance.max_wip_prs, 5);
        assert!(config.roles.contains_key("spec_architect"));
        assert!(config.roles.contains_key("design_engineer"));
        assert!(config.roles.contains_key("traceability_auditor"));
    }

    #[test]
    fn test_factory_config_extended_toml_deserialization() {
        let toml_str = r#"
schema_version = "2.1"

[telemetry.otlp]
provider = "phoenix"
endpoint = "http://localhost:6006/v1/traces"
batch_timeout_ms = 500
max_queue_size = 1024
scrub_secrets = true

[storage]
provider = "sqlite"
path = "/shared/central/factory.db"

[traceability]
engine = "openfasttrace"
spec_dir = "specs"
min_coverage_pct = 98.5
enforce_test_linkage = true

[design_system]
provider = "git_only"
tokens_path = "tokens.json"
contracts_path = "contracts"
platforms = ["web", "ios"]
on_missing_platform = "fail"

[design_system.web]
catalog = "storybook"
a11y_engine = "axe_core"
visual_regression = "lost_pixel"

[governance]
max_wip_prs = 3
slo_defense_error_budget_min = 0.95
budget_usd_per_kr = 100.0

[roles.custom_role]
driver = "claude"
model_tier = "frontier"
capabilities = ["git"]
"#;
        let config: FactoryConfig =
            toml::from_str(toml_str).expect("Failed to parse extended TOML");
        assert_eq!(config.telemetry.otlp.provider, "phoenix");
        assert_eq!(config.telemetry.otlp.batch_timeout_ms, 500);
        assert_eq!(
            config.storage.path,
            PathBuf::from("/shared/central/factory.db")
        );
        assert_eq!(config.traceability.min_coverage_pct, 98.5);
        assert_eq!(config.design_system.platforms, vec!["web", "ios"]);
        assert_eq!(config.governance.max_wip_prs, 3);
        assert!(config.roles.contains_key("custom_role"));
        assert_eq!(config.roles.get("custom_role").unwrap().driver, "claude");
    }
}
