use anyhow::Result;
use base64::engine::general_purpose::STANDARD as BASE64;
use base64::Engine;
use ed25519_dalek::VerifyingKey;
use serde::{Deserialize, Serialize};

use crate::bom::models::FactoryBom;
use crate::bom::signing::verify_factory_bom;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct BomPolicy {
    #[serde(default = "default_true")]
    pub require_valid_signature: bool,

    #[serde(default)]
    pub trusted_public_keys: Vec<String>,

    #[serde(default)]
    pub enforce_pinned_dependencies: bool,

    #[serde(default)]
    pub require_clean_git_tree: bool,

    #[serde(default)]
    pub allowed_rustc_versions: Vec<String>,

    #[serde(default)]
    pub allowed_python_versions: Vec<String>,

    #[serde(default)]
    pub allowed_tart_builds: Vec<String>,

    #[serde(default)]
    pub allowed_incus_fingerprints: Vec<String>,

    #[serde(default)]
    pub enforce_skill_merkle_match: bool,

    #[serde(default)]
    pub expected_skill_merkle_root: Option<String>,
}

fn default_true() -> bool {
    true
}

impl Default for BomPolicy {
    fn default() -> Self {
        Self {
            require_valid_signature: true,
            trusted_public_keys: Vec::new(),
            enforce_pinned_dependencies: false,
            require_clean_git_tree: false,
            allowed_rustc_versions: Vec::new(),
            allowed_python_versions: Vec::new(),
            allowed_tart_builds: Vec::new(),
            allowed_incus_fingerprints: Vec::new(),
            enforce_skill_merkle_match: false,
            expected_skill_merkle_root: None,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct PolicyReport {
    pub passed: bool,
    pub violations: Vec<String>,
}

pub fn evaluate_policy(bom: &FactoryBom, policy: &BomPolicy) -> Result<PolicyReport> {
    let mut violations = Vec::new();

    // 1. Signature check
    if policy.require_valid_signature {
        match &bom.signature_info {
            None => violations.push("Policy violation: FactoryBom is unsigned".to_string()),
            Some(sig) => {
                let mut verified = false;
                if !policy.trusted_public_keys.is_empty() {
                    for key_str in &policy.trusted_public_keys {
                        let b64 = key_str.split(':').next_back().unwrap_or(key_str).trim();
                        if let Ok(bytes) = BASE64.decode(b64) {
                            if bytes.len() == 32 {
                                let mut arr = [0u8; 32];
                                arr.copy_from_slice(&bytes);
                                if let Ok(verifying_key) = VerifyingKey::from_bytes(&arr) {
                                    if verify_factory_bom(bom, Some(&verifying_key)).is_ok() {
                                        verified = true;
                                        break;
                                    }
                                }
                            }
                        }
                    }
                    if !verified {
                        violations.push(format!(
                            "Policy violation: signature key {} not in trusted_public_keys list",
                            sig.key_id
                        ));
                    }
                } else if let Err(e) = verify_factory_bom(bom, None) {
                    violations.push(format!(
                        "Policy violation: invalid BOM digest/signature: {}",
                        e
                    ));
                }
            }
        }
    }

    // 2. Clean Git tree check
    if policy.require_clean_git_tree && bom.plane_specs.git_dirty_stash_hash.is_some() {
        violations
            .push("Policy violation: build was produced from a dirty Git working tree".to_string());
    }

    // 3. Pinned dependencies check
    if policy.enforce_pinned_dependencies {
        for dep in &bom.plane_dependencies {
            if dep.checksum.is_none() {
                violations.push(format!(
                    "Policy violation: unpinned or unchecksummed dependency: {} ({})",
                    dep.name, dep.version
                ));
            }
        }
    }

    // 4. Compiler version checks
    if !policy.allowed_rustc_versions.is_empty() {
        if let Some(rustc) = bom.plane_toolchain.iter().find(|t| t.name == "rustc") {
            let matched = policy
                .allowed_rustc_versions
                .iter()
                .any(|v| rustc.version.starts_with(v));
            if !matched {
                violations.push(format!(
                    "Policy violation: rustc version '{}' not in allowed list: {:?}",
                    rustc.version, policy.allowed_rustc_versions
                ));
            }
        }
    }

    // 5. Tart IPSW build check
    if !policy.allowed_tart_builds.is_empty() {
        if let Some(ref tart) = bom.plane_substrate.tart_fingerprint {
            let matched = policy.allowed_tart_builds.contains(&tart.ipsw_build);
            if !matched {
                violations.push(format!(
                    "Policy violation: Tart IPSW build '{}' not in allowed list: {:?}",
                    tart.ipsw_build, policy.allowed_tart_builds
                ));
            }
        }
    }

    // 6. Incus image fingerprint check
    if !policy.allowed_incus_fingerprints.is_empty() {
        if let Some(ref incus) = bom.plane_substrate.incus_fingerprint {
            let matched = policy
                .allowed_incus_fingerprints
                .iter()
                .any(|fp| incus.image_fingerprint.starts_with(fp));
            if !matched {
                violations.push(format!(
                    "Policy violation: Incus image fingerprint '{}' not in allowed list: {:?}",
                    incus.image_fingerprint, policy.allowed_incus_fingerprints
                ));
            }
        }
    }

    // 7. Agent skills Merkle root match
    if policy.enforce_skill_merkle_match {
        if let Some(ref expected) = policy.expected_skill_merkle_root {
            let actual = bom
                .plane_agentic
                .skills_merkle_root
                .as_deref()
                .unwrap_or("");
            if actual != expected {
                violations.push(format!(
                    "Policy violation: skills Merkle root mismatch: expected '{}', got '{}'",
                    expected, actual
                ));
            }
        }
    }

    let passed = violations.is_empty();
    Ok(PolicyReport { passed, violations })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::bom::models::{
        AgenticSupplyChain, DependencyComponent, DependencyType, MachineIdentity, ProxySupplyChain,
        SandboxIsolationInfo, SpecStrategySupplyChain, SubstrateEnvironment, ToolchainComponent,
    };
    use crate::bom::signing::{generate_keypair, sign_factory_bom};
    use std::collections::BTreeMap;

    fn create_signed_bom() -> FactoryBom {
        let key = generate_keypair();
        let bom = FactoryBom {
            bom_id: "policy-bom-1".to_string(),
            created_at: "2026-11-24T09:00:00Z".to_string(),
            target_name: "pa-container".to_string(),
            target_version: "2.0.0".to_string(),
            task_id: Some("task-1".to_string()),
            trace_id: Some("trace-1".to_string()),
            commit_sha: Some("commit-1".to_string()),
            originating_machine: MachineIdentity {
                host_os: "macos".to_string(),
                host_kernel: "24.1.0".to_string(),
                host_arch: "arm64".to_string(),
                machine_uuid: "uuid-1".to_string(),
            },
            plane_dependencies: vec![DependencyComponent {
                name: "tokio".to_string(),
                version: "1.40.0".to_string(),
                purl: Some("pkg:cargo/tokio@1.40.0".to_string()),
                checksum: Some("sha256:tokio123".to_string()),
                dep_type: DependencyType::RuntimeDirect,
                ecosystem: "cargo".to_string(),
            }],
            plane_toolchain: vec![ToolchainComponent {
                name: "rustc".to_string(),
                version: "1.82.0".to_string(),
                commit_or_build: None,
                path: Some("/usr/bin/rustc".to_string()),
                binary_sha256: Some("sha256:rustc123".to_string()),
                kind: "compiler".to_string(),
            }],
            plane_substrate: SubstrateEnvironment {
                backend: "macos-tart".to_string(),
                tart_fingerprint: None,
                incus_fingerprint: None,
                guest_os_release: BTreeMap::new(),
                sandbox_isolation: SandboxIsolationInfo {
                    kind: "seatbelt".to_string(),
                    version_or_abi: None,
                    ruleset_hash: None,
                },
            },
            plane_agentic: AgenticSupplyChain {
                runner_name: Some("pi".to_string()),
                runner_version: Some("2.0.0".to_string()),
                runner_sha256: None,
                skills_merkle_root: Some("merkle-root-abc".to_string()),
                role_name: Some("architect".to_string()),
                prompt_hashes: BTreeMap::new(),
                model_id: Some("claude-3-7-sonnet".to_string()),
                model_mode: Some("cloud".to_string()),
                local_weights_sha256: None,
            },
            plane_proxy: ProxySupplyChain {
                proxy_version: Some("2.0.0".to_string()),
                proxy_commit: None,
                addon_hashes: BTreeMap::new(),
                allowlist_ruleset_hash: None,
            },
            plane_specs: SpecStrategySupplyChain {
                git_tree_sha: None,
                git_commit_sha: None,
                git_dirty_stash_hash: None,
                okr_hashes: BTreeMap::new(),
                spec_hashes: BTreeMap::new(),
                design_token_hash: None,
                design_contract_hashes: BTreeMap::new(),
                traceability_summary: None,
            },
            artifacts: Vec::new(),
            signature_info: None,
        };

        let (signed, _, _) = sign_factory_bom(bom, &key).unwrap();
        signed
    }

    #[test]
    fn test_policy_evaluation_success() {
        let bom = create_signed_bom();
        let policy = BomPolicy {
            require_valid_signature: true,
            enforce_pinned_dependencies: true,
            require_clean_git_tree: true,
            allowed_rustc_versions: vec!["1.82".to_string()],
            enforce_skill_merkle_match: true,
            expected_skill_merkle_root: Some("merkle-root-abc".to_string()),
            ..Default::default()
        };

        let report = evaluate_policy(&bom, &policy).unwrap();
        assert!(report.passed);
        assert!(report.violations.is_empty());
    }

    #[test]
    fn test_policy_evaluation_violations() {
        let mut bom = create_signed_bom();
        bom.plane_specs.git_dirty_stash_hash = Some("dirty-hash-123".to_string());
        bom.plane_dependencies.push(DependencyComponent {
            name: "unpinned-pkg".to_string(),
            version: "0.1.0".to_string(),
            purl: None,
            checksum: None,
            dep_type: DependencyType::RuntimeTransitive,
            ecosystem: "cargo".to_string(),
        });

        let policy = BomPolicy {
            require_valid_signature: false,
            enforce_pinned_dependencies: true,
            require_clean_git_tree: true,
            allowed_rustc_versions: vec!["1.83".to_string()],
            ..Default::default()
        };

        let report = evaluate_policy(&bom, &policy).unwrap();
        assert!(!report.passed);
        assert_eq!(report.violations.len(), 3);
        assert!(report
            .violations
            .iter()
            .any(|v| v.contains("dirty Git working tree")));
        assert!(report.violations.iter().any(|v| v.contains("unpinned")));
        assert!(report
            .violations
            .iter()
            .any(|v| v.contains("rustc version")));
    }
}
