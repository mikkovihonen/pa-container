use anyhow::Result;
use serde_json::json;

use crate::bom::models::FactoryBom;

/// Converts a FactoryBom into a CycloneDX 1.6 JSON representation.
pub fn to_cyclonedx_json(bom: &FactoryBom) -> Result<serde_json::Value> {
    // 1. Metadata tools components
    let mut tool_components = Vec::new();
    for tool in &bom.plane_toolchain {
        let mut tool_json = json!({
            "type": "application",
            "name": tool.name,
            "version": tool.version,
        });
        if let Some(ref sha) = tool.binary_sha256 {
            tool_json["hashes"] = json!([{
                "alg": "SHA-256",
                "content": sha
            }]);
        }
        if let Some(ref commit) = tool.commit_or_build {
            tool_json["description"] = json!(commit);
        }
        tool_components.push(tool_json);
    }

    // Add pa-container orchestrator
    tool_components.push(json!({
        "type": "application",
        "name": "pa-container",
        "version": "2.0.0",
        "description": "Next-Generation Multi-Agent Software Factory Orchestrator"
    }));

    // 2. Third-party components
    let mut components = Vec::new();
    for dep in &bom.plane_dependencies {
        let mut comp = json!({
            "type": "library",
            "name": dep.name,
            "version": dep.version,
        });
        if let Some(ref purl) = dep.purl {
            comp["purl"] = json!(purl);
        }
        if let Some(ref chk) = dep.checksum {
            let alg = if chk.starts_with("sha512-") {
                "SHA-512"
            } else {
                "SHA-256"
            };
            comp["hashes"] = json!([{
                "alg": alg,
                "content": chk
            }]);
        }
        components.push(comp);
    }

    // Add substrate component
    components.push(json!({
        "type": "operating-system",
        "name": bom.plane_substrate.backend,
        "description": format!("Host: {} {} ({})",
            bom.originating_machine.host_os,
            bom.originating_machine.host_kernel,
            bom.originating_machine.host_arch
        )
    }));

    // 3. Primary component (first artifact or target)
    let main_artifact = bom.artifacts.first();
    let mut primary_component = json!({
        "type": "application",
        "name": bom.target_name,
        "version": bom.target_version,
    });
    if let Some(art) = main_artifact {
        primary_component["hashes"] = json!([
            { "alg": "SHA-256", "content": art.sha256 },
            { "alg": "SHA-512", "content": art.sha512 }
        ]);
    }

    // 4. Formulation: workflows, steps, and toolchain
    let formulation = json!({
        "workflows": [
            {
                "bom-ref": "factory-build-workflow",
                "uid": bom.bom_id,
                "name": "PA-Container Factory Build & Verification Pipeline",
                "tasks": [
                    {
                        "bom-ref": "task-plan",
                        "name": "Specification & Planning Gate (Gate 1)",
                        "task-id": bom.task_id
                    },
                    {
                        "bom-ref": "task-execute",
                        "name": "Agentic Implementation Execution",
                        "agent-role": bom.plane_agentic.role_name,
                        "model": bom.plane_agentic.model_id
                    },
                    {
                        "bom-ref": "task-verify",
                        "name": "Traceability & Quality Gate (Gate 2)",
                        "trace-id": bom.trace_id
                    }
                ]
            }
        ]
    });

    let serial_number = format!("urn:uuid:{}", bom.bom_id);

    let mut doc = json!({
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": serial_number,
        "version": 1,
        "metadata": {
            "timestamp": bom.created_at,
            "component": primary_component,
            "tools": {
                "components": tool_components
            },
            "properties": [
                { "name": "pa:bom_id", "value": bom.bom_id },
                { "name": "pa:machine_uuid", "value": bom.originating_machine.machine_uuid },
                { "name": "pa:task_id", "value": bom.task_id.clone().unwrap_or_default() },
                { "name": "pa:trace_id", "value": bom.trace_id.clone().unwrap_or_default() },
                { "name": "pa:commit_sha", "value": bom.commit_sha.clone().unwrap_or_default() }
            ]
        },
        "components": components,
        "formulation": formulation
    });

    if let Some(ref sig_info) = bom.signature_info {
        doc["signature"] = json!({
            "algorithm": sig_info.algorithm,
            "keyId": sig_info.key_id,
            "publicKey": {
                "type": "Ed25519"
            },
            "value": sig_info.signature_b64
        });
    }

    Ok(doc)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::bom::models::{
        AgenticSupplyChain, DependencyComponent, DependencyType, MachineIdentity, OutputArtifact,
        ProxySupplyChain, SandboxIsolationInfo, SignatureInfo, SpecStrategySupplyChain,
        SubstrateEnvironment, ToolchainComponent,
    };
    use std::collections::BTreeMap;

    #[test]
    fn test_to_cyclonedx_json() {
        let bom = FactoryBom {
            bom_id: "test-bom-1".to_string(),
            created_at: "2026-11-24T09:00:00Z".to_string(),
            target_name: "my-app".to_string(),
            target_version: "1.0.0".to_string(),
            task_id: Some("task-123".to_string()),
            trace_id: Some("trace-456".to_string()),
            commit_sha: Some("commit-789".to_string()),
            originating_machine: MachineIdentity {
                host_os: "macos".to_string(),
                host_kernel: "24.1.0".to_string(),
                host_arch: "arm64".to_string(),
                machine_uuid: "uuid-1".to_string(),
            },
            plane_dependencies: vec![DependencyComponent {
                name: "serde".to_string(),
                version: "1.0.210".to_string(),
                purl: Some("pkg:cargo/serde@1.0.210".to_string()),
                checksum: Some("sha256:abc".to_string()),
                dep_type: DependencyType::RuntimeDirect,
                ecosystem: "cargo".to_string(),
            }],
            plane_toolchain: vec![ToolchainComponent {
                name: "rustc".to_string(),
                version: "1.82.0".to_string(),
                commit_or_build: Some("commit:abc".to_string()),
                path: Some("/usr/bin/rustc".to_string()),
                binary_sha256: Some("sha256:123".to_string()),
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
                sca_summary: None,
                design_gate_summary: None,
                eval_summary: None,
            },
            artifacts: vec![OutputArtifact {
                name: "my-app".to_string(),
                path: "target/release/my-app".to_string(),
                sha256: "sha256-art".to_string(),
                sha512: "sha512-art".to_string(),
                size_bytes: 1024,
                mime_type: Some("application/octet-stream".to_string()),
                artifact_type: "binary".to_string(),
            }],
            signature_info: Some(SignatureInfo {
                bom_digest: "sha256:digest".to_string(),
                key_id: "pa-factory-ed25519-abc".to_string(),
                signature_b64: "c2lnbmF0dXJl".to_string(),
                algorithm: "Ed25519".to_string(),
            }),
        };

        let cdx = to_cyclonedx_json(&bom).unwrap();
        assert_eq!(cdx["bomFormat"], "CycloneDX");
        assert_eq!(cdx["specVersion"], "1.6");
        assert_eq!(cdx["metadata"]["component"]["name"], "my-app");
        assert!(cdx["signature"].is_object());
        assert_eq!(cdx["signature"]["keyId"], "pa-factory-ed25519-abc");
    }
}
