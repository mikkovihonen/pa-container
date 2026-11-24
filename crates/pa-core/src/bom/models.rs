use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct FactoryBom {
    pub bom_id: String,
    pub created_at: String,
    pub target_name: String,
    pub target_version: String,
    pub task_id: Option<String>,
    pub trace_id: Option<String>,
    pub commit_sha: Option<String>,

    pub originating_machine: MachineIdentity,

    // The 6 Planes
    pub plane_dependencies: Vec<DependencyComponent>,
    pub plane_toolchain: Vec<ToolchainComponent>,
    pub plane_substrate: SubstrateEnvironment,
    pub plane_agentic: AgenticSupplyChain,
    pub plane_proxy: ProxySupplyChain,
    pub plane_specs: SpecStrategySupplyChain,

    // End-product artifacts
    pub artifacts: Vec<OutputArtifact>,

    // Cryptographic signature & canonical digest (optional when unsigned, present when signed)
    #[serde(skip_serializing_if = "Option::is_none")]
    pub signature_info: Option<SignatureInfo>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct MachineIdentity {
    pub host_os: String,
    pub host_kernel: String,
    pub host_arch: String,
    pub machine_uuid: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub enum DependencyType {
    RuntimeDirect,
    RuntimeTransitive,
    Build,
    Dev,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct DependencyComponent {
    pub name: String,
    pub version: String,
    pub purl: Option<String>,
    pub checksum: Option<String>,
    pub dep_type: DependencyType,
    pub ecosystem: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ToolchainComponent {
    pub name: String,
    pub version: String,
    pub commit_or_build: Option<String>,
    pub path: Option<String>,
    pub binary_sha256: Option<String>,
    pub kind: String, // "compiler", "linker", "interpreter", "runtime", "sdk", "linter"
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct SubstrateEnvironment {
    pub backend: String, // "macos-tart", "linux-incus", "host"
    pub tart_fingerprint: Option<TartSubstrateFingerprint>,
    pub incus_fingerprint: Option<IncusSubstrateFingerprint>,
    pub guest_os_release: BTreeMap<String, String>,
    pub sandbox_isolation: SandboxIsolationInfo,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct TartSubstrateFingerprint {
    pub ipsw_build: String,
    pub config_hash: String,
    pub disk_digest: String,
    pub darwin_version: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct IncusSubstrateFingerprint {
    pub image_fingerprint: String,
    pub config_hash: String,
    pub rootfs_digest: String,
    pub kernel_version: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct SandboxIsolationInfo {
    pub kind: String, // "seatbelt", "landlock", "none"
    pub version_or_abi: Option<String>,
    pub ruleset_hash: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct AgenticSupplyChain {
    pub runner_name: Option<String>,
    pub runner_version: Option<String>,
    pub runner_sha256: Option<String>,
    pub skills_merkle_root: Option<String>,
    pub role_name: Option<String>,
    pub prompt_hashes: BTreeMap<String, String>,
    pub model_id: Option<String>,
    pub model_mode: Option<String>, // "cloud" | "local-llama"
    pub local_weights_sha256: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ProxySupplyChain {
    pub proxy_version: Option<String>,
    pub proxy_commit: Option<String>,
    pub addon_hashes: BTreeMap<String, String>,
    pub allowlist_ruleset_hash: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct SpecStrategySupplyChain {
    pub git_tree_sha: Option<String>,
    pub git_commit_sha: Option<String>,
    pub git_dirty_stash_hash: Option<String>,
    pub okr_hashes: BTreeMap<String, String>,
    pub spec_hashes: BTreeMap<String, String>,
    pub design_token_hash: Option<String>,
    pub design_contract_hashes: BTreeMap<String, String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub traceability_summary: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct OutputArtifact {
    pub name: String,
    pub path: String,
    pub sha256: String,
    pub sha512: String,
    pub size_bytes: u64,
    pub mime_type: Option<String>,
    pub artifact_type: String, // "binary", "archive", "package", "bundle"
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct SignatureInfo {
    pub bom_digest: String, // sha256:<hex> of canonical JCS payload (excluding signature_info)
    pub key_id: String,     // pa-factory-ed25519-<short-hash>
    pub signature_b64: String, // base64 Ed25519 signature
    pub algorithm: String,  // "Ed25519"
}
