use anyhow::{anyhow, Context, Result};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};

use crate::manifest::AcpServerBinding;
use crate::schema::RoleSpec;

pub mod emitters;
pub use emitters::*;

/// Schema version for the Canonical Skill Intermediate Representation
pub const SKILL_IR_SCHEMA_VERSION: u32 = 1;

fn default_schema_version_int() -> u32 {
    SKILL_IR_SCHEMA_VERSION
}

fn default_mcp_transport() -> String {
    "stdio".to_string()
}

/// Parsed skill document extracted from SKILL.md
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct SkillDoc {
    pub name: String,
    #[serde(default)]
    pub description: String,
    #[serde(default)]
    pub triggers: Vec<String>,
    #[serde(default)]
    pub required_mcp: Vec<String>,
    #[serde(default)]
    pub tags: Vec<String>,
    pub body: String,
    pub sha256: String,
    pub source_path: PathBuf,
}

/// Normalized MCP/ACP context server specification for agents
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct McpServerSpec {
    pub id: String,
    #[serde(default = "default_mcp_transport")]
    pub transport: String,
    pub command: String,
    #[serde(default)]
    pub args: Vec<String>,
    #[serde(default)]
    pub env: BTreeMap<String, String>,
    #[serde(default)]
    pub read_only: bool,
}

/// Role execution context accompanying a compiled bundle
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct RoleContext {
    pub role_name: String,
    pub driver: String,
    pub model_tier: String,
    #[serde(default)]
    pub allowed_write_paths: Vec<String>,
    #[serde(default)]
    pub skills_merkle_root: String,
}

/// Canonical, versioned Intermediate Representation consumed by all emitters
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct CompiledSkillBundle {
    #[serde(default = "default_schema_version_int")]
    pub schema_version: u32,
    pub role: RoleContext,
    #[serde(default)]
    pub skills: Vec<SkillDoc>,
    #[serde(default)]
    pub mcp_servers: Vec<McpServerSpec>,
}

impl CompiledSkillBundle {
    /// Serialize the canonical bundle to formatted JSON
    pub fn to_json_pretty(&self) -> Result<String> {
        serde_json::to_string_pretty(self)
            .context("Failed to serialize CompiledSkillBundle to JSON")
    }

    /// Deserialize a canonical bundle from JSON
    pub fn from_json(json_str: &str) -> Result<Self> {
        serde_json::from_str(json_str)
            .context("Failed to deserialize CompiledSkillBundle from JSON")
    }
}

/// Lightweight parser for YAML frontmatter in Markdown files
#[derive(Debug, Default, Clone)]
struct ParsedFrontmatter {
    name: Option<String>,
    description: Option<String>,
    triggers: Vec<String>,
    required_mcp: Vec<String>,
    tags: Vec<String>,
    body: String,
}

fn clean_val(v: &str) -> String {
    let trimmed = v.trim();
    if (trimmed.starts_with('"') && trimmed.ends_with('"') && trimmed.len() >= 2)
        || (trimmed.starts_with('\'') && trimmed.ends_with('\'') && trimmed.len() >= 2)
    {
        trimmed[1..trimmed.len() - 1].to_string()
    } else {
        trimmed.to_string()
    }
}

fn parse_yaml_list(val: &str) -> Vec<String> {
    let trimmed = val.trim();
    if trimmed.starts_with('[') && trimmed.ends_with(']') {
        let inner = &trimmed[1..trimmed.len() - 1];
        inner
            .split(',')
            .map(clean_val)
            .filter(|s| !s.is_empty())
            .collect()
    } else if !trimmed.is_empty() {
        vec![clean_val(trimmed)]
    } else {
        Vec::new()
    }
}

fn parse_frontmatter(content: &str) -> ParsedFrontmatter {
    let trimmed = content.trim_start();
    if !trimmed.starts_with("---") {
        return ParsedFrontmatter {
            name: None,
            description: None,
            triggers: Vec::new(),
            required_mcp: Vec::new(),
            tags: Vec::new(),
            body: content.to_string(),
        };
    }

    // Find the ending `---`
    let after_first = &trimmed[3..];
    let end_idx = match after_first.find("\n---") {
        Some(idx) => idx,
        None => {
            return ParsedFrontmatter {
                name: None,
                description: None,
                triggers: Vec::new(),
                required_mcp: Vec::new(),
                tags: Vec::new(),
                body: content.to_string(),
            };
        }
    };

    let yaml_block = &after_first[..end_idx];
    let remainder = &after_first[end_idx + 4..];
    let body = remainder.trim_start_matches('\r').trim_start_matches('\n');

    let mut parsed = ParsedFrontmatter {
        body: body.to_string(),
        ..Default::default()
    };

    let mut current_list_key: Option<String> = None;

    for line in yaml_block.lines() {
        let line_trimmed = line.trim();
        if line_trimmed.is_empty() || line_trimmed.starts_with('#') {
            continue;
        }

        // Check for list item under current list key
        if line_trimmed.starts_with('-') && current_list_key.is_some() {
            let item = clean_val(&line_trimmed[1..]);
            if !item.is_empty() {
                match current_list_key.as_deref() {
                    Some("triggers") => parsed.triggers.push(item),
                    Some("required_mcp") => parsed.required_mcp.push(item),
                    Some("tags") => parsed.tags.push(item),
                    _ => {}
                }
            }
            continue;
        }

        if let Some((k, v)) = line.split_once(':') {
            let key = k.trim();
            let val = v.trim();

            match key {
                "name" => {
                    parsed.name = Some(clean_val(val));
                    current_list_key = None;
                }
                "description" => {
                    parsed.description = Some(clean_val(val));
                    current_list_key = None;
                }
                "triggers" => {
                    if val.is_empty() {
                        current_list_key = Some("triggers".to_string());
                    } else {
                        parsed.triggers = parse_yaml_list(val);
                        current_list_key = None;
                    }
                }
                "required_mcp" => {
                    if val.is_empty() {
                        current_list_key = Some("required_mcp".to_string());
                    } else {
                        parsed.required_mcp = parse_yaml_list(val);
                        current_list_key = None;
                    }
                }
                "tags" => {
                    if val.is_empty() {
                        current_list_key = Some("tags".to_string());
                    } else {
                        parsed.tags = parse_yaml_list(val);
                        current_list_key = None;
                    }
                }
                _ => {
                    current_list_key = None;
                }
            }
        }
    }

    parsed
}

/// Infer fallback skill name from file path or markdown headings
fn infer_skill_name(path: &Path, content: &str) -> String {
    // 1. Try to inspect parent directory
    if let Some(parent) = path.parent() {
        let parent_name = parent
            .file_name()
            .and_then(|n| n.to_str())
            .unwrap_or_default();
        if parent_name == "skill" || parent_name == "skills" {
            if let Some(grandparent) = parent.parent() {
                let gp_name = grandparent
                    .file_name()
                    .and_then(|n| n.to_str())
                    .unwrap_or_default();
                if !gp_name.is_empty() {
                    return gp_name.to_string();
                }
            }
        } else if !parent_name.is_empty() {
            return parent_name.to_string();
        }
    }

    // 2. Try to inspect first markdown header
    for line in content.lines() {
        let t = line.trim();
        if let Some(rest) = t.strip_prefix('#') {
            let header = rest.trim_start_matches('#').trim();
            // Look for backticks e.g. `pi` or `git`
            if let Some(start) = header.find('`') {
                if let Some(end) = header[start + 1..].find('`') {
                    let code = &header[start + 1..start + 1 + end];
                    if !code.is_empty() {
                        return code.to_string();
                    }
                }
            }
            if !header.is_empty() {
                return header
                    .to_lowercase()
                    .replace(' ', "-")
                    .chars()
                    .filter(|c| c.is_alphanumeric() || *c == '-' || *c == '_')
                    .collect();
            }
        }
    }

    "unknown-skill".to_string()
}

/// Infer fallback description from first non-header line
fn infer_skill_description(body: &str) -> String {
    for line in body.lines() {
        let t = line.trim();
        if !t.is_empty() && !t.starts_with('#') && !t.starts_with("```") {
            return t.to_string();
        }
    }
    String::new()
}

/// Parse a SKILL.md file into a SkillDoc with deterministic hash
pub fn parse_skill_file(path: &Path) -> Result<SkillDoc> {
    let bytes =
        fs::read(path).with_context(|| format!("Failed to read skill at {}", path.display()))?;
    let content = String::from_utf8_lossy(&bytes);

    let parsed = parse_frontmatter(&content);
    let name = parsed
        .name
        .unwrap_or_else(|| infer_skill_name(path, &content));
    let description = parsed
        .description
        .unwrap_or_else(|| infer_skill_description(&parsed.body));

    let mut hasher = Sha256::new();
    hasher.update(&bytes);
    let sha256 = hex::encode(hasher.finalize());

    Ok(SkillDoc {
        name,
        description,
        triggers: parsed.triggers,
        required_mcp: parsed.required_mcp,
        tags: parsed.tags,
        body: parsed.body,
        sha256,
        source_path: path.to_path_buf(),
    })
}

/// Deterministic Merkle Root calculation for a slice of skills
pub fn compute_skills_merkle_root(skills: &[SkillDoc]) -> String {
    if skills.is_empty() {
        return String::new();
    }
    let mut hashes: Vec<String> = skills.iter().map(|s| s.sha256.clone()).collect();
    hashes.sort();

    let mut hasher = Sha256::new();
    for h in hashes {
        hasher.update(h.as_bytes());
    }
    hex::encode(hasher.finalize())
}

/// Loader for discovering, filtering, and preparing canonical skill bundles
pub struct SkillLoader;

impl SkillLoader {
    /// Discover all available skills across packages and workspace
    /// Workspace-local skills (`.pi/skills/<name>/SKILL.md`) override package skills
    pub fn discover_all_skills(
        repo_root: &Path,
        packages_dir: &Path,
    ) -> Result<BTreeMap<String, SkillDoc>> {
        let mut skills = BTreeMap::new();

        // 1. Scan packages_dir
        if packages_dir.is_dir() {
            Self::scan_dir_for_skills(packages_dir, &mut skills)?;
        }

        // 2. Scan workspace-local .pi/skills/ (highest precedence)
        let local_skills_dir = repo_root.join(".pi").join("skills");
        if local_skills_dir.is_dir() {
            Self::scan_dir_for_skills(&local_skills_dir, &mut skills)?;
        }

        // 3. Scan workspace-local .gemini/skills/ if present
        let gemini_skills_dir = repo_root.join(".gemini").join("skills");
        if gemini_skills_dir.is_dir() {
            Self::scan_dir_for_skills(&gemini_skills_dir, &mut skills)?;
        }

        Ok(skills)
    }

    fn scan_dir_for_skills(dir: &Path, out: &mut BTreeMap<String, SkillDoc>) -> Result<()> {
        let mut stack = vec![dir.to_path_buf()];

        while let Some(current) = stack.pop() {
            if let Ok(entries) = fs::read_dir(&current) {
                for entry in entries.flatten() {
                    let path = entry.path();
                    if path.is_dir() {
                        stack.push(path);
                    } else if path.is_file() {
                        let file_name = path
                            .file_name()
                            .and_then(|n| n.to_str())
                            .unwrap_or_default();
                        if file_name.eq_ignore_ascii_case("SKILL.md") {
                            if let Ok(doc) = parse_skill_file(&path) {
                                // Overwrite existing (later scans like workspace override packages)
                                out.insert(doc.name.clone(), doc);
                            }
                        }
                    }
                }
            }
        }
        Ok(())
    }

    /// Load and compile a bundle for a specific role following least-privilege scoping
    pub fn load_for_role(
        repo_root: &Path,
        packages_dir: &Path,
        role_name: &str,
        role_spec: &RoleSpec,
        acp_bindings: &[AcpServerBinding],
    ) -> Result<CompiledSkillBundle> {
        let all_skills = Self::discover_all_skills(repo_root, packages_dir)?;

        // Role-scoped filtering:
        // If role_spec.skills is empty, 0 skills are compiled (least privilege principle)
        let mut compiled_skills = Vec::new();
        for req_skill in &role_spec.skills {
            if let Some(skill_doc) = all_skills.get(req_skill) {
                compiled_skills.push(skill_doc.clone());
            } else {
                return Err(anyhow!(
                    "Skill '{}' requested by role '{}' not found in workspace (.pi/skills/) or packages ({})",
                    req_skill,
                    role_name,
                    packages_dir.display()
                ));
            }
        }

        // Sort skills deterministically by name
        compiled_skills.sort_by(|a, b| a.name.cmp(&b.name));

        // Compute Merkle root
        let skills_merkle_root = compute_skills_merkle_root(&compiled_skills);

        // Convert ACP bindings to McpServerSpec
        let mut mcp_servers = Vec::new();
        for binding in acp_bindings {
            mcp_servers.push(McpServerSpec {
                id: binding.name.clone(),
                transport: "stdio".to_string(),
                command: binding.command.display().to_string(),
                args: binding.args.clone(),
                env: BTreeMap::new(),
                read_only: binding.service == "read",
            });
        }
        mcp_servers.sort_by(|a, b| a.id.cmp(&b.id));

        let role_ctx = RoleContext {
            role_name: role_name.to_string(),
            driver: role_spec.driver.clone(),
            model_tier: role_spec.model_tier.clone(),
            allowed_write_paths: role_spec.capabilities.clone(),
            skills_merkle_root,
        };

        Ok(CompiledSkillBundle {
            schema_version: SKILL_IR_SCHEMA_VERSION,
            role: role_ctx,
            skills: compiled_skills,
            mcp_servers,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn test_parse_frontmatter_standard() {
        let content = r#"---
name: sample-skill
description: "A sample skill for testing"
triggers: ["build", "test"]
required_mcp: ["telemetry"]
tags: ["core", "dev"]
---

# Sample Skill

Body instructions go here.
"#;
        let parsed = parse_frontmatter(content);
        assert_eq!(parsed.name.as_deref(), Some("sample-skill"));
        assert_eq!(
            parsed.description.as_deref(),
            Some("A sample skill for testing")
        );
        assert_eq!(parsed.triggers, vec!["build", "test"]);
        assert_eq!(parsed.required_mcp, vec!["telemetry"]);
        assert_eq!(parsed.tags, vec!["core", "dev"]);
        assert!(parsed.body.starts_with("# Sample Skill"));
    }

    #[test]
    fn test_parse_frontmatter_bullet_lists() {
        let content = r#"---
name: list-skill
triggers:
  - run
  - exec
tags:
  - fast
---
Body text.
"#;
        let parsed = parse_frontmatter(content);
        assert_eq!(parsed.name.as_deref(), Some("list-skill"));
        assert_eq!(parsed.triggers, vec!["run", "exec"]);
        assert_eq!(parsed.tags, vec!["fast"]);
        assert_eq!(parsed.body.trim(), "Body text.");
    }

    #[test]
    fn test_workspace_override_precedence() {
        let temp = tempdir().unwrap();
        let root = temp.path();

        let pkg_skill_dir = root.join("packages/capabilities/test_skill/skill");
        fs::create_dir_all(&pkg_skill_dir).unwrap();
        fs::write(
            pkg_skill_dir.join("SKILL.md"),
            "---\nname: test_skill\ndescription: Package version\n---\nPackage body\n",
        )
        .unwrap();

        let local_skill_dir = root.join(".pi/skills/test_skill");
        fs::create_dir_all(&local_skill_dir).unwrap();
        fs::write(
            local_skill_dir.join("SKILL.md"),
            "---\nname: test_skill\ndescription: Workspace override version\n---\nWorkspace body\n",
        )
        .unwrap();

        let discovered = SkillLoader::discover_all_skills(root, &root.join("packages")).unwrap();
        assert_eq!(discovered.len(), 1);
        let skill = discovered.get("test_skill").unwrap();
        assert_eq!(skill.description, "Workspace override version");
        assert_eq!(skill.body.trim(), "Workspace body");
    }

    #[test]
    fn test_role_scoped_filtering_least_privilege() {
        let temp = tempdir().unwrap();
        let root = temp.path();

        let s1 = root.join(".pi/skills/skill_one");
        let s2 = root.join(".pi/skills/skill_two");
        fs::create_dir_all(&s1).unwrap();
        fs::create_dir_all(&s2).unwrap();
        fs::write(s1.join("SKILL.md"), "---\nname: skill_one\n---\nBody 1\n").unwrap();
        fs::write(s2.join("SKILL.md"), "---\nname: skill_two\n---\nBody 2\n").unwrap();

        // Role with no skills -> 0 compiled skills
        let empty_role = RoleSpec::default();
        let bundle_empty = SkillLoader::load_for_role(
            root,
            &root.join("packages"),
            "empty_role",
            &empty_role,
            &[],
        )
        .unwrap();
        assert_eq!(bundle_empty.skills.len(), 0);
        assert_eq!(bundle_empty.role.skills_merkle_root, "");

        // Role with explicit skill
        let scoped_role = RoleSpec {
            skills: vec!["skill_one".to_string()],
            ..Default::default()
        };
        let bundle_scoped = SkillLoader::load_for_role(
            root,
            &root.join("packages"),
            "scoped_role",
            &scoped_role,
            &[],
        )
        .unwrap();
        assert_eq!(bundle_scoped.skills.len(), 1);
        assert_eq!(bundle_scoped.skills[0].name, "skill_one");
        assert!(!bundle_scoped.role.skills_merkle_root.is_empty());

        // Role with missing skill -> Error
        let missing_role = RoleSpec {
            skills: vec!["non_existent_skill".to_string()],
            ..Default::default()
        };
        let err = SkillLoader::load_for_role(
            root,
            &root.join("packages"),
            "missing_role",
            &missing_role,
            &[],
        );
        assert!(err.is_err());
    }

    #[test]
    fn test_merkle_root_determinism() {
        let s1 = SkillDoc {
            name: "alpha".to_string(),
            description: "A".to_string(),
            triggers: vec![],
            required_mcp: vec![],
            tags: vec![],
            body: "body a".to_string(),
            sha256: "1111111111111111111111111111111111111111111111111111111111111111".to_string(),
            source_path: PathBuf::from("a"),
        };
        let s2 = SkillDoc {
            name: "beta".to_string(),
            description: "B".to_string(),
            triggers: vec![],
            required_mcp: vec![],
            tags: vec![],
            body: "body b".to_string(),
            sha256: "2222222222222222222222222222222222222222222222222222222222222222".to_string(),
            source_path: PathBuf::from("b"),
        };

        let root1 = compute_skills_merkle_root(&[s1.clone(), s2.clone()]);
        let root2 = compute_skills_merkle_root(&[s2.clone(), s1.clone()]);
        assert_eq!(root1, root2);
        assert!(!root1.is_empty());
    }
}
