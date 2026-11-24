use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::fs;
use std::path::Path;
use std::process::Command;

use crate::bom::models::SpecStrategySupplyChain;

pub fn collect_spec_strategy_supply_chain(root_dir: &Path) -> SpecStrategySupplyChain {
    // 1. Git state
    let git_commit_sha = Command::new("git")
        .args(["rev-parse", "HEAD"])
        .current_dir(root_dir)
        .output()
        .ok()
        .and_then(|o| {
            if o.status.success() {
                Some(String::from_utf8_lossy(&o.stdout).trim().to_string())
            } else {
                None
            }
        });

    let git_tree_sha = Command::new("git")
        .args(["rev-parse", "HEAD^{tree}"])
        .current_dir(root_dir)
        .output()
        .ok()
        .and_then(|o| {
            if o.status.success() {
                Some(String::from_utf8_lossy(&o.stdout).trim().to_string())
            } else {
                None
            }
        });

    // Check dirty state / stash hash
    let git_dirty_stash_hash = Command::new("git")
        .args(["status", "--porcelain"])
        .current_dir(root_dir)
        .output()
        .ok()
        .and_then(|o| {
            if o.status.success() {
                let stdout = String::from_utf8_lossy(&o.stdout);
                if !stdout.trim().is_empty() {
                    let mut hasher = Sha256::new();
                    hasher.update(stdout.as_bytes());
                    Some(hex::encode(hasher.finalize()))
                } else {
                    None
                }
            } else {
                None
            }
        });

    // 2. OKRs
    let mut okr_hashes = BTreeMap::new();
    let okrs_dir = root_dir.join("docs/okrs");
    if okrs_dir.is_dir() {
        hash_dir_files(&okrs_dir, &mut okr_hashes);
    }

    // 3. Specs
    let mut spec_hashes = BTreeMap::new();
    let specs_dir = root_dir.join("docs/specs");
    if specs_dir.is_dir() {
        hash_dir_files(&specs_dir, &mut spec_hashes);
    }
    let features_dir = root_dir.join(".pa/features");
    if features_dir.is_dir() {
        hash_dir_files(&features_dir, &mut spec_hashes);
    }

    // 4. Design tokens & contracts
    let tokens_file = root_dir.join("design/tokens/tokens.json");
    let design_token_hash = if tokens_file.is_file() {
        fs::read(&tokens_file).ok().map(|b| {
            let mut hasher = Sha256::new();
            hasher.update(&b);
            hex::encode(hasher.finalize())
        })
    } else {
        None
    };

    let mut design_contract_hashes = BTreeMap::new();
    let contracts_dir = root_dir.join("design/contracts");
    if contracts_dir.is_dir() {
        hash_dir_files(&contracts_dir, &mut design_contract_hashes);
    }

    SpecStrategySupplyChain {
        git_tree_sha,
        git_commit_sha,
        git_dirty_stash_hash,
        okr_hashes,
        spec_hashes,
        design_token_hash,
        design_contract_hashes,
    }
}

fn hash_dir_files(dir: &Path, out: &mut BTreeMap<String, String>) {
    if let Ok(entries) = fs::read_dir(dir) {
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
                    out.insert(name, hex::encode(hasher.finalize()));
                }
            } else if p.is_dir() {
                hash_dir_files(&p, out);
            }
        }
    }
}
