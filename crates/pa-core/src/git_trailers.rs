use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use std::path::Path;
use std::process::Command;

#[derive(Debug, Clone, Serialize, Deserialize, Default, PartialEq)]
pub struct GitProvenanceMetadata {
    pub task_id: String,
    pub trace_id: String,
    #[serde(default)]
    pub objective_id: Option<String>,
    #[serde(default)]
    pub kr_ids: Vec<String>,
    #[serde(default)]
    pub req_ids: Vec<String>,
    #[serde(default)]
    pub traceability: Option<String>,
    #[serde(default)]
    pub design_system: Option<String>,
    #[serde(default)]
    pub design_refs: Vec<String>,
    #[serde(default)]
    pub design_platforms: Vec<String>,
    #[serde(default)]
    pub design_gate: Option<String>,
    #[serde(default)]
    pub agent_role: Option<String>,
    #[serde(default)]
    pub model: Option<String>,
    #[serde(default)]
    pub cost_usd: Option<f64>,
}

impl GitProvenanceMetadata {
    pub fn format_trailers(&self) -> String {
        let mut lines = Vec::new();
        if !self.task_id.is_empty() {
            lines.push(format!("X-PA-Task-ID: {}", self.task_id));
        }
        if !self.trace_id.is_empty() {
            lines.push(format!("X-PA-Trace-ID: {}", self.trace_id));
        }
        if let Some(ref obj) = self.objective_id {
            lines.push(format!("X-PA-Objective: {}", obj));
        }
        if !self.kr_ids.is_empty() {
            lines.push(format!("X-PA-Key-Results: {}", self.kr_ids.join(",")));
        }
        if !self.req_ids.is_empty() {
            lines.push(format!("X-PA-Requirements: {}", self.req_ids.join(",")));
        }
        if let Some(ref trace) = self.traceability {
            lines.push(format!("X-PA-Traceability: {}", trace));
        }
        if let Some(ref ds) = self.design_system {
            lines.push(format!("X-PA-Design-System: {}", ds));
        }
        if !self.design_refs.is_empty() {
            lines.push(format!("X-PA-Design-Refs: {}", self.design_refs.join(",")));
        }
        if !self.design_platforms.is_empty() {
            lines.push(format!(
                "X-PA-Design-Platforms: {}",
                self.design_platforms.join(",")
            ));
        }
        if let Some(ref gate) = self.design_gate {
            lines.push(format!("X-PA-Design-Gate: {}", gate));
        }
        if let Some(ref role) = self.agent_role {
            lines.push(format!("X-PA-Agent: {}", role));
        }
        if let Some(ref model) = self.model {
            lines.push(format!("X-PA-Model: {}", model));
        }
        if let Some(cost) = self.cost_usd {
            lines.push(format!("X-PA-Cost-USD: {:.4}", cost));
        }

        lines.join("\n")
    }

    pub fn parse(msg: &str) -> Self {
        let mut meta = Self::default();

        for line in msg.lines() {
            let trimmed = line.trim();
            if let Some((k, v)) = trimmed.split_once(':') {
                let key = k.trim();
                let val = v.trim();
                match key {
                    "X-PA-Task-ID" => meta.task_id = val.to_string(),
                    "X-PA-Trace-ID" => meta.trace_id = val.to_string(),
                    "X-PA-Objective" => meta.objective_id = Some(val.to_string()),
                    "X-PA-Key-Results" => {
                        meta.kr_ids = val
                            .split(',')
                            .map(|s| s.trim().to_string())
                            .filter(|s| !s.is_empty())
                            .collect();
                    }
                    "X-PA-Requirements" => {
                        meta.req_ids = val
                            .split(',')
                            .map(|s| s.trim().to_string())
                            .filter(|s| !s.is_empty())
                            .collect();
                    }
                    "X-PA-Traceability" => meta.traceability = Some(val.to_string()),
                    "X-PA-Design-System" => meta.design_system = Some(val.to_string()),
                    "X-PA-Design-Refs" => {
                        meta.design_refs = val
                            .split(',')
                            .map(|s| s.trim().to_string())
                            .filter(|s| !s.is_empty())
                            .collect();
                    }
                    "X-PA-Design-Platforms" => {
                        meta.design_platforms = val
                            .split(',')
                            .map(|s| s.trim().to_string())
                            .filter(|s| !s.is_empty())
                            .collect();
                    }
                    "X-PA-Design-Gate" => meta.design_gate = Some(val.to_string()),
                    "X-PA-Agent" => meta.agent_role = Some(val.to_string()),
                    "X-PA-Model" => meta.model = Some(val.to_string()),
                    "X-PA-Cost-USD" => meta.cost_usd = val.parse::<f64>().ok(),
                    _ => {}
                }
            }
        }

        meta
    }
}

pub fn stamp_commit_message(original_msg: &str, meta: &GitProvenanceMetadata) -> String {
    let trailers = meta.format_trailers();
    if trailers.is_empty() {
        return original_msg.to_string();
    }

    let trimmed = original_msg.trim_end();
    format!("{}\n\n{}\n", trimmed, trailers)
}

pub fn stamp_head_commit(repo_path: &Path, meta: &GitProvenanceMetadata) -> Result<()> {
    // Get existing commit message
    let out = Command::new("git")
        .args(["log", "-1", "--format=%B"])
        .current_dir(repo_path)
        .output()
        .context("Failed to get current git commit message")?;

    if !out.status.success() {
        anyhow::bail!("git log failed: {}", String::from_utf8_lossy(&out.stderr));
    }

    let original_msg = String::from_utf8_lossy(&out.stdout);
    let new_msg = stamp_commit_message(&original_msg, meta);

    // Amend commit with updated message
    let amend = Command::new("git")
        .args(["commit", "--amend", "-m", &new_msg])
        .current_dir(repo_path)
        .output()
        .context("Failed to amend git commit with trailers")?;

    if !amend.status.success() {
        anyhow::bail!(
            "git commit --amend failed: {}",
            String::from_utf8_lossy(&amend.stderr)
        );
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_format_and_parse_trailers() {
        let meta = GitProvenanceMetadata {
            task_id: "feat-auth-001".to_string(),
            trace_id: "4bf92f3577b34da6a3ce929d0e0e4736".to_string(),
            objective_id: Some("OBJ-2026-Q4-SEC".to_string()),
            kr_ids: vec!["KR-AUTH-01".to_string(), "KR-AUTH-02".to_string()],
            req_ids: vec!["REQ-AUTH-TOKEN-ROTATION".to_string()],
            traceability: Some("openfasttrace:100%".to_string()),
            design_system: Some("git_only:v1.2.0".to_string()),
            design_refs: vec!["web:button-primary".to_string()],
            design_platforms: vec!["web".to_string(), "ios".to_string()],
            design_gate: Some("passed".to_string()),
            agent_role: Some("design_engineer".to_string()),
            model: Some("claude-3-7-sonnet".to_string()),
            cost_usd: Some(0.1420),
        };

        let formatted = meta.format_trailers();
        assert!(formatted.contains("X-PA-Task-ID: feat-auth-001"));
        assert!(formatted.contains("X-PA-Key-Results: KR-AUTH-01,KR-AUTH-02"));
        assert!(formatted.contains("X-PA-Design-Platforms: web,ios"));

        let commit_msg = stamp_commit_message("feat: add token rotation", &meta);
        let parsed = GitProvenanceMetadata::parse(&commit_msg);

        assert_eq!(parsed.task_id, "feat-auth-001");
        assert_eq!(parsed.objective_id.as_deref(), Some("OBJ-2026-Q4-SEC"));
        assert_eq!(parsed.kr_ids, vec!["KR-AUTH-01", "KR-AUTH-02"]);
        assert_eq!(parsed.design_gate.as_deref(), Some("passed"));
        assert_eq!(parsed.cost_usd, Some(0.1420));
    }
}
