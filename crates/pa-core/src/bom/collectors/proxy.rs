use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::fs;
use std::path::Path;

use crate::bom::models::ProxySupplyChain;

pub fn collect_proxy_supply_chain(root_dir: &Path) -> ProxySupplyChain {
    let proxy_dir = root_dir.join("coding-agent-proxy");
    let mut addon_hashes = BTreeMap::new();

    let addons_dir = proxy_dir.join("addons");
    if addons_dir.is_dir() {
        if let Ok(entries) = fs::read_dir(&addons_dir) {
            for entry in entries.flatten() {
                let p = entry.path();
                if p.is_file() {
                    let name = p
                        .file_name()
                        .unwrap_or_default()
                        .to_string_lossy()
                        .to_string();
                    if let Ok(bytes) = fs::read(&p) {
                        let mut hasher = Sha256::new();
                        hasher.update(&bytes);
                        addon_hashes.insert(name, hex::encode(hasher.finalize()));
                    }
                } else if p.is_dir() {
                    // check subdirectory e.g. otlp_exporter
                    let sub_name = p
                        .file_name()
                        .unwrap_or_default()
                        .to_string_lossy()
                        .to_string();
                    let main_py = p.join(format!("{}.py", sub_name));
                    if main_py.is_file() {
                        if let Ok(bytes) = fs::read(&main_py) {
                            let mut hasher = Sha256::new();
                            hasher.update(&bytes);
                            addon_hashes
                                .insert(format!("{}.py", sub_name), hex::encode(hasher.finalize()));
                        }
                    }
                }
            }
        }
    }

    // Proxy main script
    let proxy_py = proxy_dir.join("proxy.py");
    if proxy_py.is_file() {
        if let Ok(bytes) = fs::read(&proxy_py) {
            let mut hasher = Sha256::new();
            hasher.update(&bytes);
            addon_hashes.insert("proxy.py".to_string(), hex::encode(hasher.finalize()));
        }
    }

    // Allowlist ruleset hash
    let mut allowlist_ruleset_hash = None;
    let allowlist_toml = root_dir.join("allowlist.toml");
    if allowlist_toml.is_file() {
        if let Ok(bytes) = fs::read(&allowlist_toml) {
            let mut hasher = Sha256::new();
            hasher.update(&bytes);
            allowlist_ruleset_hash = Some(hex::encode(hasher.finalize()));
        }
    }

    ProxySupplyChain {
        proxy_version: Some("2.0.0".to_string()),
        proxy_commit: None,
        addon_hashes,
        allowlist_ruleset_hash,
    }
}
