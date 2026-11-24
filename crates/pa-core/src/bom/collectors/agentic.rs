use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
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

    // 2. Merkle root of skills via canonical SkillLoader
    let packages_dir = root_dir.join("pa_packages");
    let skills_merkle_root = if let Ok(skills_map) =
        crate::skills::SkillLoader::discover_all_skills(root_dir, &packages_dir)
    {
        if !skills_map.is_empty() {
            let skill_docs: Vec<crate::skills::SkillDoc> = skills_map.into_values().collect();
            let root = crate::skills::compute_skills_merkle_root(&skill_docs);
            if !root.is_empty() {
                Some(root)
            } else {
                None
            }
        } else {
            None
        }
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
