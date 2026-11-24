use anyhow::Result;
use base64::engine::general_purpose::STANDARD as BASE64;
use base64::Engine;
use serde_json::json;

use crate::bom::models::FactoryBom;

/// Converts a FactoryBom into a signed SLSA v1.0 Provenance in-toto DSSE envelope.
pub fn to_slsa_dsse_json(bom: &FactoryBom) -> Result<serde_json::Value> {
    // 1. Subjects: Output artifacts
    let mut subjects = Vec::new();
    for art in &bom.artifacts {
        subjects.push(json!({
            "name": art.name,
            "digest": {
                "sha256": art.sha256,
                "sha512": art.sha512
            }
        }));
    }
    if subjects.is_empty() {
        subjects.push(json!({
            "name": bom.target_name,
            "digest": {
                "sha256": bom.signature_info.as_ref().map(|s| &s.bom_digest).unwrap_or(&"0000".to_string())
            }
        }));
    }

    // 2. Resolved dependencies / materials
    let mut resolved_deps = Vec::new();

    // Source Git repo
    if let Some(ref sha) = bom.commit_sha {
        resolved_deps.push(json!({
            "uri": "git+https://github.com/mikkovihonen/pa-container",
            "digest": { "gitCommit": sha }
        }));
    }

    // Toolchain components
    for tool in &bom.plane_toolchain {
        let mut dep = json!({
            "uri": format!("tool:{}", tool.name),
            "version": tool.version,
        });
        if let Some(ref sha) = tool.binary_sha256 {
            dep["digest"] = json!({ "sha256": sha });
        }
        resolved_deps.push(dep);
    }

    // Agent skills Merkle root
    if let Some(ref merkle) = bom.plane_agentic.skills_merkle_root {
        resolved_deps.push(json!({
            "uri": "skills://.pi/skills",
            "digest": { "sha256": merkle }
        }));
    }

    // Substrate base image
    if let Some(ref tart) = bom.plane_substrate.tart_fingerprint {
        resolved_deps.push(json!({
            "uri": format!("substrate://macos-tart/ipsw-{}", tart.ipsw_build),
            "digest": { "diskSha256": tart.disk_digest, "configSha256": tart.config_hash }
        }));
    } else if let Some(ref incus) = bom.plane_substrate.incus_fingerprint {
        resolved_deps.push(json!({
            "uri": "substrate://linux-incus/cloud-image",
            "digest": { "imageFingerprint": incus.image_fingerprint, "rootfsSha256": incus.rootfs_digest }
        }));
    }

    // 3. in-toto Statement
    let statement = json!({
        "_type": "https://in-toto.io/Statement/v1",
        "subject": subjects,
        "predicateType": "https://slsa.dev/provenance/v1",
        "predicate": {
            "buildDefinition": {
                "buildType": "https://pa-container.dev/attestation/factory-build/v1",
                "externalParameters": {
                    "targetName": bom.target_name,
                    "targetVersion": bom.target_version,
                    "taskId": bom.task_id,
                    "traceId": bom.trace_id,
                    "commitSha": bom.commit_sha,
                },
                "internalParameters": {
                    "backend": bom.plane_substrate.backend,
                    "machineUuid": bom.originating_machine.machine_uuid,
                    "agentRole": bom.plane_agentic.role_name,
                    "modelId": bom.plane_agentic.model_id,
                    "modelMode": bom.plane_agentic.model_mode,
                },
                "resolvedDependencies": resolved_deps
            },
            "runDetails": {
                "builder": {
                    "id": "https://pa-container.dev/builder/factory@v2.0"
                },
                "metadata": {
                    "invocationId": bom.bom_id,
                    "startedOn": bom.created_at,
                }
            }
        }
    });

    // 4. Wrap in DSSE envelope
    let statement_bytes = serde_json::to_vec(&statement)?;
    let payload_b64 = BASE64.encode(&statement_bytes);

    let mut signatures = Vec::new();
    if let Some(ref sig_info) = bom.signature_info {
        signatures.push(json!({
            "keyid": sig_info.key_id,
            "sig": sig_info.signature_b64
        }));
    }

    let envelope = json!({
        "payloadType": "application/vnd.in-toto+json",
        "payload": payload_b64,
        "signatures": signatures
    });

    Ok(envelope)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::bom::models::{
        AgenticSupplyChain, MachineIdentity, OutputArtifact, ProxySupplyChain,
        SandboxIsolationInfo, SignatureInfo, SpecStrategySupplyChain, SubstrateEnvironment,
    };
    use std::collections::BTreeMap;

    #[test]
    fn test_to_slsa_dsse_json() {
        let bom = FactoryBom {
            bom_id: "test-bom-slsa".to_string(),
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
            plane_dependencies: Vec::new(),
            plane_toolchain: Vec::new(),
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
            },
            artifacts: vec![OutputArtifact {
                name: "my-bin".to_string(),
                path: "target/release/my-bin".to_string(),
                sha256: "art-sha256".to_string(),
                sha512: "art-sha512".to_string(),
                size_bytes: 2048,
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

        let envelope = to_slsa_dsse_json(&bom).unwrap();
        assert_eq!(envelope["payloadType"], "application/vnd.in-toto+json");
        assert!(envelope["payload"].is_string());
        let sigs = envelope["signatures"].as_array().unwrap();
        assert_eq!(sigs.len(), 1);
        assert_eq!(sigs[0]["keyid"], "pa-factory-ed25519-abc");

        // Decode payload
        let payload_bytes = BASE64
            .decode(envelope["payload"].as_str().unwrap())
            .unwrap();
        let stmt: serde_json::Value = serde_json::from_slice(&payload_bytes).unwrap();
        assert_eq!(stmt["_type"], "https://in-toto.io/Statement/v1");
        assert_eq!(stmt["predicateType"], "https://slsa.dev/provenance/v1");
        assert_eq!(stmt["subject"][0]["name"], "my-bin");
    }
}
