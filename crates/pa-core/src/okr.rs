use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fs;
use std::path::Path;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ObjectiveSpec {
    pub id: String,
    pub title: String,
    #[serde(default)]
    pub owner: String,
    #[serde(default)]
    pub budget_usd: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct KeyResultSpec {
    pub id: String,
    pub title: String,
    #[serde(default)]
    pub metric_query: String,
    #[serde(default)]
    pub baseline: f64,
    #[serde(default)]
    pub target: f64,
    #[serde(default)]
    pub current: f64,
    #[serde(default)]
    pub budget_usd: f64,
    #[serde(default)]
    pub linked_reqs: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct OkrManifest {
    pub objective: ObjectiveSpec,
    #[serde(default)]
    pub key_results: Vec<KeyResultSpec>,
}

#[derive(Debug, Clone)]
pub struct OkrStore {
    pub objectives: HashMap<String, ObjectiveSpec>,
    pub key_results: HashMap<String, KeyResultSpec>,
    pub kr_to_objective: HashMap<String, String>,
    pub req_to_kr: HashMap<String, String>,
}

impl Default for OkrStore {
    fn default() -> Self {
        Self::new()
    }
}

impl OkrStore {
    pub fn new() -> Self {
        let mut store = Self {
            objectives: HashMap::new(),
            key_results: HashMap::new(),
            kr_to_objective: HashMap::new(),
            req_to_kr: HashMap::new(),
        };

        // Standard fallback objective for general engineering & maintenance
        let default_ops = ObjectiveSpec {
            id: "OBJ-OPS-MAINTENANCE".to_string(),
            title: "General Engineering & Operations Maintenance".to_string(),
            owner: "core-engineering".to_string(),
            budget_usd: 100.0,
        };
        store.objectives.insert(default_ops.id.clone(), default_ops);
        store
    }

    pub fn load_from_dir(dir: &Path) -> Result<Self> {
        let mut store = Self::new();
        if !dir.is_dir() {
            return Ok(store);
        }

        let entries = fs::read_dir(dir)
            .with_context(|| format!("Failed to read OKR directory: {}", dir.display()))?;

        for entry in entries.filter_map(|e| e.ok()) {
            let path = entry.path();
            if path.extension().and_then(|s| s.to_str()) == Some("toml") {
                let content = fs::read_to_string(&path)
                    .with_context(|| format!("Failed to read OKR manifest: {}", path.display()))?;
                let manifest: OkrManifest = toml::from_str(&content).with_context(|| {
                    format!("Failed to parse OKR manifest TOML: {}", path.display())
                })?;

                let obj_id = manifest.objective.id.clone();
                store.objectives.insert(obj_id.clone(), manifest.objective);

                for kr in manifest.key_results {
                    let kr_id = kr.id.clone();
                    store.kr_to_objective.insert(kr_id.clone(), obj_id.clone());

                    for req in &kr.linked_reqs {
                        store.req_to_kr.insert(req.clone(), kr_id.clone());
                    }

                    store.key_results.insert(kr_id, kr);
                }
            }
        }

        Ok(store)
    }

    pub fn resolve_hierarchy(&self, req_id: &str) -> (String, Vec<String>) {
        if let Some(kr_id) = self.req_to_kr.get(req_id) {
            if let Some(obj_id) = self.kr_to_objective.get(kr_id) {
                return (obj_id.clone(), vec![kr_id.clone()]);
            }
            return ("OBJ-OPS-MAINTENANCE".to_string(), vec![kr_id.clone()]);
        }

        // Check if req_id is directly a KR
        if let Some(obj_id) = self.kr_to_objective.get(req_id) {
            return (obj_id.clone(), vec![req_id.to_string()]);
        }

        ("OBJ-OPS-MAINTENANCE".to_string(), Vec::new())
    }

    pub fn get_objective(&self, obj_id: &str) -> Option<&ObjectiveSpec> {
        self.objectives.get(obj_id)
    }

    pub fn get_kr(&self, kr_id: &str) -> Option<&KeyResultSpec> {
        self.key_results.get(kr_id)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn test_okr_manifest_deserialization() {
        let toml_str = r#"
[objective]
id = "OBJ-2026-Q4-SEC"
title = "Zero-Trust Infrastructure and Token Security"
owner = "security-team"
budget_usd = 250.0

[[key_results]]
id = "KR-AUTH-01"
title = "OAuth2 Token Rotation and Exfiltration Prevention"
metric_query = "sum(auth_token_rotation_success_total)"
baseline = 0.0
target = 100.0
current = 45.0
budget_usd = 50.0
linked_reqs = ["REQ-AUTH-TOKEN-ROTATION", "REQ-AUTH-REVOCATION"]
"#;

        let manifest: OkrManifest = toml::from_str(toml_str).unwrap();
        assert_eq!(manifest.objective.id, "OBJ-2026-Q4-SEC");
        assert_eq!(manifest.key_results.len(), 1);
        assert_eq!(manifest.key_results[0].id, "KR-AUTH-01");
        assert_eq!(manifest.key_results[0].linked_reqs.len(), 2);
    }

    #[test]
    fn test_okr_store_hierarchy_resolution() {
        let td = tempdir().unwrap();
        let okr_file = td.path().join("sec_okr.toml");

        let toml_str = r#"
[objective]
id = "OBJ-2026-SEC"
title = "Security"
budget_usd = 100.0

[[key_results]]
id = "KR-SEC-01"
title = "Token Rotation"
budget_usd = 30.0
linked_reqs = ["REQ-TOKEN-01"]
"#;
        fs::write(&okr_file, toml_str).unwrap();

        let store = OkrStore::load_from_dir(td.path()).unwrap();
        assert_eq!(store.objectives.len(), 2); // OBJ-OPS-MAINTENANCE + OBJ-2026-SEC

        let (obj_id, krs) = store.resolve_hierarchy("REQ-TOKEN-01");
        assert_eq!(obj_id, "OBJ-2026-SEC");
        assert_eq!(krs, vec!["KR-SEC-01".to_string()]);

        // Fallback for unlinked req
        let (fallback_obj, fallback_krs) = store.resolve_hierarchy("REQ-UNKNOWN");
        assert_eq!(fallback_obj, "OBJ-OPS-MAINTENANCE");
        assert!(fallback_krs.is_empty());
    }
}
