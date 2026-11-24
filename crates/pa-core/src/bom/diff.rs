use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};

use crate::bom::models::FactoryBom;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct BomDiffReport {
    pub bom_a_id: String,
    pub bom_b_id: String,
    pub commit_changed: bool,
    pub target_version_changed: bool,

    // Plane 1: Dependencies
    pub added_deps: Vec<String>,
    pub removed_deps: Vec<String>,
    pub modified_deps: Vec<ModifiedItem>,

    // Plane 2: Toolchain
    pub added_tools: Vec<String>,
    pub removed_tools: Vec<String>,
    pub modified_tools: Vec<ModifiedItem>,

    // Plane 3: Substrate
    pub substrate_changes: Vec<String>,

    // Plane 4: Agentic
    pub agentic_changes: Vec<String>,

    // Plane 5: Proxy
    pub proxy_changes: Vec<String>,

    // Plane 6: Specs
    pub spec_changes: Vec<String>,

    // Artifacts
    pub artifact_changes: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ModifiedItem {
    pub name: String,
    pub old_val: String,
    pub new_val: String,
}

pub fn diff_boms(a: &FactoryBom, b: &FactoryBom) -> BomDiffReport {
    let commit_changed = a.commit_sha != b.commit_sha;
    let target_version_changed = a.target_version != b.target_version;

    // 1. Dependencies diff
    let mut map_a_deps = BTreeMap::new();
    for d in &a.plane_dependencies {
        map_a_deps.insert(&d.name, d);
    }
    let mut map_b_deps = BTreeMap::new();
    for d in &b.plane_dependencies {
        map_b_deps.insert(&d.name, d);
    }

    let all_dep_names: BTreeSet<&String> = map_a_deps
        .keys()
        .chain(map_b_deps.keys())
        .copied()
        .collect();
    let mut added_deps = Vec::new();
    let mut removed_deps = Vec::new();
    let mut modified_deps = Vec::new();

    for name in all_dep_names {
        match (map_a_deps.get(name), map_b_deps.get(name)) {
            (None, Some(new_d)) => added_deps.push(format!("{}@{}", new_d.name, new_d.version)),
            (Some(old_d), None) => removed_deps.push(format!("{}@{}", old_d.name, old_d.version)),
            (Some(old_d), Some(new_d)) => {
                if old_d.version != new_d.version || old_d.checksum != new_d.checksum {
                    modified_deps.push(ModifiedItem {
                        name: name.to_string(),
                        old_val: format!("v:{}, chk:{:?}", old_d.version, old_d.checksum),
                        new_val: format!("v:{}, chk:{:?}", new_d.version, new_d.checksum),
                    });
                }
            }
            (None, None) => {}
        }
    }

    // 2. Toolchain diff
    let mut map_a_tools = BTreeMap::new();
    for t in &a.plane_toolchain {
        map_a_tools.insert(&t.name, t);
    }
    let mut map_b_tools = BTreeMap::new();
    for t in &b.plane_toolchain {
        map_b_tools.insert(&t.name, t);
    }

    let all_tool_names: BTreeSet<&String> = map_a_tools
        .keys()
        .chain(map_b_tools.keys())
        .copied()
        .collect();
    let mut added_tools = Vec::new();
    let mut removed_tools = Vec::new();
    let mut modified_tools = Vec::new();

    for name in all_tool_names {
        match (map_a_tools.get(name), map_b_tools.get(name)) {
            (None, Some(t)) => added_tools.push(format!("{} ({})", t.name, t.version)),
            (Some(t), None) => removed_tools.push(format!("{} ({})", t.name, t.version)),
            (Some(old_t), Some(new_t)) => {
                if old_t.version != new_t.version || old_t.binary_sha256 != new_t.binary_sha256 {
                    modified_tools.push(ModifiedItem {
                        name: name.to_string(),
                        old_val: format!("v:{}, bin_sha:{:?}", old_t.version, old_t.binary_sha256),
                        new_val: format!("v:{}, bin_sha:{:?}", new_t.version, new_t.binary_sha256),
                    });
                }
            }
            (None, None) => {}
        }
    }

    // 3. Substrate diff
    let mut substrate_changes = Vec::new();
    if a.plane_substrate.backend != b.plane_substrate.backend {
        substrate_changes.push(format!(
            "Backend changed: '{}' -> '{}'",
            a.plane_substrate.backend, b.plane_substrate.backend
        ));
    }
    if a.plane_substrate.tart_fingerprint != b.plane_substrate.tart_fingerprint {
        substrate_changes.push("Tart VM fingerprint or IPSW build changed".to_string());
    }
    if a.plane_substrate.incus_fingerprint != b.plane_substrate.incus_fingerprint {
        substrate_changes.push("Incus image fingerprint or profile changed".to_string());
    }

    // 4. Agentic diff
    let mut agentic_changes = Vec::new();
    if a.plane_agentic.model_id != b.plane_agentic.model_id {
        agentic_changes.push(format!(
            "Model ID changed: {:?} -> {:?}",
            a.plane_agentic.model_id, b.plane_agentic.model_id
        ));
    }
    if a.plane_agentic.skills_merkle_root != b.plane_agentic.skills_merkle_root {
        agentic_changes.push("Agent skills directory Merkle root changed".to_string());
    }
    if a.plane_agentic.prompt_hashes != b.plane_agentic.prompt_hashes {
        agentic_changes.push("Agent prompt hashes changed".to_string());
    }

    // 5. Proxy diff
    let mut proxy_changes = Vec::new();
    if a.plane_proxy.addon_hashes != b.plane_proxy.addon_hashes {
        proxy_changes.push("Proxy addon script hashes changed".to_string());
    }
    if a.plane_proxy.allowlist_ruleset_hash != b.plane_proxy.allowlist_ruleset_hash {
        proxy_changes.push("Network allowlist ruleset hash changed".to_string());
    }

    // 6. Specs diff
    let mut spec_changes = Vec::new();
    if a.plane_specs.design_token_hash != b.plane_specs.design_token_hash {
        spec_changes.push("DTCG design tokens hash changed".to_string());
    }
    if a.plane_specs.okr_hashes != b.plane_specs.okr_hashes {
        spec_changes.push("OKRs-as-Code manifests changed".to_string());
    }
    if a.plane_specs.spec_hashes != b.plane_specs.spec_hashes {
        spec_changes.push("Requirement specification files changed".to_string());
    }

    // Artifacts diff
    let mut artifact_changes = Vec::new();
    let map_a_art: BTreeMap<&String, &String> = a
        .artifacts
        .iter()
        .map(|art| (&art.name, &art.sha256))
        .collect();
    let map_b_art: BTreeMap<&String, &String> = b
        .artifacts
        .iter()
        .map(|art| (&art.name, &art.sha256))
        .collect();

    let all_art_names: BTreeSet<&String> =
        map_a_art.keys().chain(map_b_art.keys()).copied().collect();
    for name in all_art_names {
        match (map_a_art.get(name), map_b_art.get(name)) {
            (None, Some(sha)) => {
                artifact_changes.push(format!("Added artifact: {} ({})", name, sha))
            }
            (Some(sha), None) => {
                artifact_changes.push(format!("Removed artifact: {} ({})", name, sha))
            }
            (Some(sha_a), Some(sha_b)) => {
                if sha_a != sha_b {
                    artifact_changes.push(format!(
                        "Modified artifact digest {}: {} -> {}",
                        name, sha_a, sha_b
                    ));
                }
            }
            (None, None) => {}
        }
    }

    BomDiffReport {
        bom_a_id: a.bom_id.clone(),
        bom_b_id: b.bom_id.clone(),
        commit_changed,
        target_version_changed,
        added_deps,
        removed_deps,
        modified_deps,
        added_tools,
        removed_tools,
        modified_tools,
        substrate_changes,
        agentic_changes,
        proxy_changes,
        spec_changes,
        artifact_changes,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::bom::models::{
        AgenticSupplyChain, DependencyComponent, DependencyType, MachineIdentity, OutputArtifact,
        ProxySupplyChain, SandboxIsolationInfo, SpecStrategySupplyChain, SubstrateEnvironment,
        ToolchainComponent,
    };
    use std::collections::BTreeMap;

    fn sample_bom(id: &str, rustc_ver: &str, dep_ver: &str) -> FactoryBom {
        FactoryBom {
            bom_id: id.to_string(),
            created_at: "2026-11-24T09:00:00Z".to_string(),
            target_name: "test-app".to_string(),
            target_version: "1.0.0".to_string(),
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
                version: dep_ver.to_string(),
                purl: Some(format!("pkg:cargo/tokio@{}", dep_ver)),
                checksum: Some("sha256:tokio".to_string()),
                dep_type: DependencyType::RuntimeDirect,
                ecosystem: "cargo".to_string(),
            }],
            plane_toolchain: vec![ToolchainComponent {
                name: "rustc".to_string(),
                version: rustc_ver.to_string(),
                commit_or_build: None,
                path: Some("/usr/bin/rustc".to_string()),
                binary_sha256: Some(format!("sha256:rustc-{}", rustc_ver)),
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
                skills_merkle_root: None,
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
            artifacts: vec![OutputArtifact {
                name: "test-app".to_string(),
                path: "target/release/test-app".to_string(),
                sha256: "art-sha256-a".to_string(),
                sha512: "art-sha512-a".to_string(),
                size_bytes: 100,
                mime_type: None,
                artifact_type: "binary".to_string(),
            }],
            signature_info: None,
        }
    }

    #[test]
    fn test_diff_boms() {
        let bom1 = sample_bom("bom-1", "1.81.0", "1.39.0");
        let mut bom2 = sample_bom("bom-2", "1.82.0", "1.40.0");
        bom2.artifacts[0].sha256 = "art-sha256-b".to_string();

        let report = diff_boms(&bom1, &bom2);
        assert_eq!(report.bom_a_id, "bom-1");
        assert_eq!(report.bom_b_id, "bom-2");

        assert_eq!(report.modified_deps.len(), 1);
        assert_eq!(report.modified_deps[0].name, "tokio");

        assert_eq!(report.modified_tools.len(), 1);
        assert_eq!(report.modified_tools[0].name, "rustc");

        assert_eq!(report.artifact_changes.len(), 1);
        assert!(report.artifact_changes[0].contains("Modified artifact digest"));
    }
}
