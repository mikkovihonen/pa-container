use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::fs;
use std::path::Path;

use crate::bom::collectors::toolchain::{hash_file, which_path};
use crate::bom::models::AgenticSupplyChain;

pub fn collect_agentic_supply_chain(
    root_dir: &Path,
    agent_name: Option<&str>,
    task_prompt: Option<&str>,
    model: Option<&str>,
) -> AgenticSupplyChain {
    // 1. Runner probe
    let runner_name = agent_name
        .map(|s| s.to_string())
        .or_else(|| Some("pi".to_string()));
    let (runner_version, runner_sha256) = if let Some(ref r_name) = runner_name {
        let p = which_path(r_name);
        let sha = p.as_deref().and_then(hash_file);
        (Some("2.0.0".to_string()), sha)
    } else {
        (None, None)
    };

    // 2. Merkle root of skills
    let mut skill_hashes = Vec::new();
    let skills_dir = root_dir.join(".pi/skills");
    if skills_dir.is_dir() {
        collect_dir_file_hashes(&skills_dir, &mut skill_hashes);
    }
    let gemini_skills = root_dir.join(".gemini/skills");
    if gemini_skills.is_dir() {
        collect_dir_file_hashes(&gemini_skills, &mut skill_hashes);
    }

    let skills_merkle_root = if !skill_hashes.is_empty() {
        skill_hashes.sort();
        let mut hasher = Sha256::new();
        for h in skill_hashes {
            hasher.update(h.as_bytes());
        }
        Some(hex::encode(hasher.finalize()))
    } else {
        None
    };

    // 3. Prompt hashes
    let mut prompt_hashes = BTreeMap::new();
    if let Some(prompt) = task_prompt {
        let mut hasher = Sha256::new();
        hasher.update(prompt.as_bytes());
        prompt_hashes.insert("task_prompt".to_string(), hex::encode(hasher.finalize()));
    }

    // Role manifests
    let role_name = agent_name.map(|s| s.to_string());
    let model_id = model
        .map(|s| s.to_string())
        .or_else(|| Some("claude-3-7-sonnet".to_string()));
    let model_mode = if model_id.as_deref().unwrap_or("").starts_with("llama") {
        Some("local-llama".to_string())
    } else {
        Some("cloud".to_string())
    };

    AgenticSupplyChain {
        runner_name,
        runner_version,
        runner_sha256,
        skills_merkle_root,
        role_name,
        prompt_hashes,
        model_id,
        model_mode,
        local_weights_sha256: None,
    }
}

fn collect_dir_file_hashes(dir: &Path, out: &mut Vec<String>) {
    if let Ok(entries) = fs::read_dir(dir) {
        for entry in entries.flatten() {
            let p = entry.path();
            if p.is_file() {
                if let Ok(bytes) = fs::read(&p) {
                    let mut hasher = Sha256::new();
                    hasher.update(&bytes);
                    out.push(hex::encode(hasher.finalize()));
                }
            } else if p.is_dir() {
                collect_dir_file_hashes(&p, out);
            }
        }
    }
}
