use anyhow::{bail, Context, Result};
use base64::engine::general_purpose::STANDARD as BASE64;
use base64::Engine;
use ed25519_dalek::{Signature, Signer, SigningKey, Verifier, VerifyingKey};
use rand::rngs::OsRng;
use std::fs;
use std::path::{Path, PathBuf};

use crate::bom::canonical::{compute_canonical_sha256, to_canonical_json_bytes};
use crate::bom::models::{FactoryBom, SignatureInfo};

/// Generates a new cryptographically random Ed25519 signing key.
pub fn generate_keypair() -> SigningKey {
    SigningKey::generate(&mut OsRng)
}

/// Derives a standard key identifier for a given verifying key: `pa-factory-ed25519-<short-hex>`
pub fn derive_key_id(verifying_key: &VerifyingKey) -> String {
    let key_bytes = verifying_key.as_bytes();
    let short_hex = hex::encode(&key_bytes[..4]);
    format!("pa-factory-ed25519-{}", short_hex)
}

/// Signs arbitrary payload bytes and returns the base64-encoded signature.
pub fn sign_payload(signing_key: &SigningKey, payload: &[u8]) -> String {
    let signature = signing_key.sign(payload);
    BASE64.encode(signature.to_bytes())
}

/// Verifies a base64-encoded Ed25519 signature against arbitrary payload bytes.
pub fn verify_signature(
    verifying_key: &VerifyingKey,
    payload: &[u8],
    signature_b64: &str,
) -> Result<()> {
    let sig_bytes = BASE64
        .decode(signature_b64.trim())
        .context("Failed to decode base64 signature")?;
    if sig_bytes.len() != 64 {
        bail!(
            "Invalid Ed25519 signature length: expected 64 bytes, got {}",
            sig_bytes.len()
        );
    }
    let mut arr = [0u8; 64];
    arr.copy_from_slice(&sig_bytes);
    let signature = Signature::from_bytes(&arr);
    verifying_key
        .verify(payload, &signature)
        .context("Ed25519 signature verification failed")
}

/// Resolves or initializes an Ed25519 signing key.
/// 1. Checks `PA_SIGNING_KEY` environment variable (32-byte hex or base64 seed).
/// 2. If `PA_DISABLE_KEYRING` is not set, tries OS Keyring.
/// 3. Checks key file path (defaulting to `.pa/keys/factory_ed25519.key`), creating if requested or if missing.
pub fn load_or_create_signing_key(key_path: Option<&Path>) -> Result<SigningKey> {
    // 1. Check PA_SIGNING_KEY env
    if let Ok(val) = std::env::var("PA_SIGNING_KEY") {
        let trimmed = val.trim();
        if !trimmed.is_empty() {
            if let Ok(bytes) = hex::decode(trimmed) {
                if bytes.len() == 32 {
                    let mut arr = [0u8; 32];
                    arr.copy_from_slice(&bytes);
                    return Ok(SigningKey::from_bytes(&arr));
                }
            }
            if let Ok(bytes) = BASE64.decode(trimmed) {
                if bytes.len() == 32 {
                    let mut arr = [0u8; 32];
                    arr.copy_from_slice(&bytes);
                    return Ok(SigningKey::from_bytes(&arr));
                }
            }
        }
    }

    // 2. Check Keyring if not disabled
    if std::env::var("PA_DISABLE_KEYRING").unwrap_or_default() != "1"
        && std::env::var("PA_TEST_MODE").unwrap_or_default() != "1"
    {
        let entry = keyring::Entry::new("pa-container", "factory-signing-key");
        if let Ok(entry) = entry {
            if let Ok(secret) = entry.get_password() {
                if let Ok(bytes) = hex::decode(secret.trim()) {
                    if bytes.len() == 32 {
                        let mut arr = [0u8; 32];
                        arr.copy_from_slice(&bytes);
                        return Ok(SigningKey::from_bytes(&arr));
                    }
                }
            }
        }
    }

    // 3. Fallback to file path
    let default_path = PathBuf::from(".pa/keys/factory_ed25519.key");
    let path = key_path.unwrap_or(&default_path);

    if path.is_file() {
        let content = fs::read_to_string(path)
            .with_context(|| format!("Failed to read signing key from {}", path.display()))?;
        let trimmed = content.trim();
        let bytes = hex::decode(trimmed)
            .or_else(|_| BASE64.decode(trimmed))
            .with_context(|| {
                format!(
                    "Invalid hex or base64 in signing key file {}",
                    path.display()
                )
            })?;
        if bytes.len() == 32 {
            let mut arr = [0u8; 32];
            arr.copy_from_slice(&bytes);
            return Ok(SigningKey::from_bytes(&arr));
        }
        bail!(
            "Invalid key length in {}: expected 32 bytes, got {}",
            path.display(),
            bytes.len()
        );
    }

    // If file doesn't exist, generate a new key and save it
    let new_key = generate_keypair();
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    let hex_key = hex::encode(new_key.to_bytes());
    fs::write(path, format!("{}\n", hex_key))?;

    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let perms = fs::Permissions::from_mode(0o600);
        let _ = fs::set_permissions(path, perms);
    }

    Ok(new_key)
}

/// Deterministically signs a FactoryBom.
/// 1. Strips `signature_info` and serializes to canonical RFC 8785 bytes.
/// 2. Calculates `bom_digest` (sha256).
/// 3. Signs the canonical bytes with the given `SigningKey`.
/// 4. Attaches `SignatureInfo` to the BOM and returns `(signed_bom, signature_b64, bom_digest)`.
pub fn sign_factory_bom(
    mut bom: FactoryBom,
    signing_key: &SigningKey,
) -> Result<(FactoryBom, String, String)> {
    bom.signature_info = None;

    let canonical_bytes = to_canonical_json_bytes(&bom)?;
    let bom_digest = compute_canonical_sha256(&bom)?;
    let verifying_key = signing_key.verifying_key();
    let key_id = derive_key_id(&verifying_key);
    let signature_b64 = sign_payload(signing_key, &canonical_bytes);

    bom.signature_info = Some(SignatureInfo {
        bom_digest: bom_digest.clone(),
        key_id,
        signature_b64: signature_b64.clone(),
        algorithm: "Ed25519".to_string(),
    });

    Ok((bom, signature_b64, bom_digest))
}

/// Verifies a signed FactoryBom against a provided or embedded public key.
pub fn verify_factory_bom(
    bom: &FactoryBom,
    trusted_public_key: Option<&VerifyingKey>,
) -> Result<()> {
    let sig_info = bom
        .signature_info
        .as_ref()
        .context("FactoryBom is unsigned (missing signature_info)")?;

    // Create a copy without signature_info
    let mut unsigned_copy = bom.clone();
    unsigned_copy.signature_info = None;

    let canonical_bytes = to_canonical_json_bytes(&unsigned_copy)?;
    let calculated_digest = compute_canonical_sha256(&unsigned_copy)?;

    if calculated_digest != sig_info.bom_digest {
        bail!(
            "BOM digest mismatch: expected {}, calculated {}",
            sig_info.bom_digest,
            calculated_digest
        );
    }

    if let Some(trusted_key) = trusted_public_key {
        verify_signature(trusted_key, &canonical_bytes, &sig_info.signature_b64)?;
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::bom::models::{
        AgenticSupplyChain, MachineIdentity, ProxySupplyChain, SandboxIsolationInfo,
        SpecStrategySupplyChain, SubstrateEnvironment,
    };
    use std::collections::BTreeMap;

    fn create_test_bom() -> FactoryBom {
        FactoryBom {
            bom_id: "test-bom-123".to_string(),
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
                machine_uuid: "uuid-123".to_string(),
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
                runner_version: Some("1.0.0".to_string()),
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
            artifacts: Vec::new(),
            signature_info: None,
        }
    }

    #[test]
    fn test_signing_and_verification() {
        let key = generate_keypair();
        let bom = create_test_bom();

        let (signed_bom, sig_b64, digest) = sign_factory_bom(bom, &key).unwrap();
        assert!(!sig_b64.is_empty());
        assert!(digest.starts_with("sha256:"));
        assert!(signed_bom.signature_info.is_some());

        let verifying_key = key.verifying_key();
        assert!(verify_factory_bom(&signed_bom, Some(&verifying_key)).is_ok());

        // Tamper with a metadata field
        let mut tampered_bom = signed_bom.clone();
        tampered_bom.created_at = "2026-11-24T09:00:01Z".to_string();
        assert!(verify_factory_bom(&tampered_bom, Some(&verifying_key)).is_err());
    }
}
