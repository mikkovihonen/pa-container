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
    pub sca_gate: Option<String>,
    #[serde(default)]
    pub eval_verdict: Option<String>,
    #[serde(default)]
    pub eval_score: Option<f64>,
    #[serde(default)]
    pub agent_role: Option<String>,
    #[serde(default)]
    pub model: Option<String>,
    #[serde(default)]
    pub model_tier: Option<String>,
    #[serde(default)]
    pub cost_usd: Option<f64>,
    #[serde(default)]
    pub bom_id: Option<String>,
    #[serde(default)]
    pub bom_digest: Option<String>,
    #[serde(default)]
    pub bom_signature: Option<String>,
    #[serde(default)]
    pub bom_key_id: Option<String>,
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
        if let Some(ref sca) = self.sca_gate {
            lines.push(format!("X-PA-SCA-Gate: {}", sca));
        }
        if let Some(ref ev) = self.eval_verdict {
            lines.push(format!("X-PA-Eval-Verdict: {}", ev));
        }
        if let Some(score) = self.eval_score {
            lines.push(format!("X-PA-Eval-Score: {:.2}", score));
        }
        if let Some(ref role) = self.agent_role {
            lines.push(format!("X-PA-Agent: {}", role));
        }
        if let Some(ref model) = self.model {
            lines.push(format!("X-PA-Model: {}", model));
        }
        if let Some(ref tier) = self.model_tier {
            lines.push(format!("X-PA-Model-Tier: {}", tier));
        }
        if let Some(cost) = self.cost_usd {
            lines.push(format!("X-PA-Cost-USD: {:.4}", cost));
        }
        if let Some(ref bid) = self.bom_id {
            lines.push(format!("X-PA-BOM-ID: {}", bid));
        }
        if let Some(ref bdigest) = self.bom_digest {
            lines.push(format!("X-PA-BOM-Digest: {}", bdigest));
        }
        if let Some(ref bsig) = self.bom_signature {
            lines.push(format!("X-PA-BOM-Signature: {}", bsig));
        }
        if let Some(ref bkey) = self.bom_key_id {
            lines.push(format!("X-PA-BOM-Key-ID: {}", bkey));
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
                    "X-PA-SCA-Gate" => meta.sca_gate = Some(val.to_string()),
                    "X-PA-Eval-Verdict" => meta.eval_verdict = Some(val.to_string()),
                    "X-PA-Eval-Score" => meta.eval_score = val.parse::<f64>().ok(),
                    "X-PA-Agent" => meta.agent_role = Some(val.to_string()),
                    "X-PA-Model" => meta.model = Some(val.to_string()),
                    "X-PA-Model-Tier" => meta.model_tier = Some(val.to_string()),
                    "X-PA-Cost-USD" => meta.cost_usd = val.parse::<f64>().ok(),
                    "X-PA-BOM-ID" => meta.bom_id = Some(val.to_string()),
                    "X-PA-BOM-Digest" => meta.bom_digest = Some(val.to_string()),
                    "X-PA-BOM-Signature" => meta.bom_signature = Some(val.to_string()),
                    "X-PA-BOM-Key-ID" => meta.bom_key_id = Some(val.to_string()),
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

pub fn format_traceability_trailer(report: &crate::traceability::TraceabilityReport) -> String {
    let outcome = if report.is_compliant { "pass" } else { "fail" };
    let total_tests = report.tests_passed + report.tests_failed + report.tests_unexecuted;

    let test_part = if total_tests > 0 {
        format!(", {}/{} tests passed", report.tests_passed, total_tests)
    } else {
        String::new()
    };

    let cov_part = if let Some(cov) = report.line_coverage_pct {
        format!(", {:.1}% line cov", cov)
    } else {
        String::new()
    };

    format!(
        "{}={} ({:.0}% covered{}{})",
        report.engine, outcome, report.coverage_pct, test_part, cov_part
    )
}

pub fn format_design_gate_trailer(report: &crate::design::DesignGateReport) -> String {
    if report.provider == "none" {
        return "tokens=skip, drift=skip, a11y=skip, visual-diff=skip".to_string();
    }

    let tokens_status = if report.violations.iter().any(|v| {
        v.rule == "unresolved_contract_token"
            || v.rule == "stale_compiled_tokens"
            || v.rule == "missing_token_compiler"
    }) {
        "fail"
    } else {
        "pass"
    };

    let drift_status = if report
        .violations
        .iter()
        .any(|v| v.rule == "raw_primitive_violation")
    {
        "drift-detected"
    } else {
        "pass"
    };

    let blocking_a11y = report
        .a11y_violations
        .iter()
        .filter(|a| a.is_blocking())
        .count();
    let a11y_part = if blocking_a11y > 0 {
        format!(
            "a11y=fail ({} blocking, {} total)",
            blocking_a11y,
            report.a11y_violations.len()
        )
    } else {
        format!("a11y=pass ({} violations)", report.a11y_violations.len())
    };

    let visual_part = if !report.visual_diff_failures.is_empty() {
        format!(
            "visual-diff={:.2}% ({} failed)",
            report.visual_diff_pct * 100.0,
            report.visual_diff_failures.len()
        )
    } else {
        format!("visual-diff={:.2}%", report.visual_diff_pct * 100.0)
    };

    let review_part = if report.needs_design_review {
        ", needs-design-review"
    } else {
        ""
    };

    format!(
        "tokens={}, drift={}, {}, {}{}",
        tokens_status, drift_status, a11y_part, visual_part, review_part
    )
}

pub fn format_sca_gate_trailer(report: &crate::sca::ScaGateReport) -> String {
    if !report.is_compliant {
        format!(
            "fail ({} blocking, {} total, scanner: {})",
            report.blocking_vulnerabilities.len(),
            report.vulnerabilities_found,
            report.scanner
        )
    } else if report.vulnerabilities_found > 0 {
        format!(
            "pass ({} advisories, scanner: {})",
            report.vulnerabilities_found, report.scanner
        )
    } else {
        format!("pass (scanner: {})", report.scanner)
    }
}

pub fn format_eval_verdicts_trailer(
    verdicts: &[crate::evals::EvalVerdict],
) -> (Option<String>, Option<f64>) {
    let active_verdicts: Vec<_> = verdicts.iter().filter(|v| !v.skipped).collect();
    if active_verdicts.is_empty() {
        return (None, None);
    }

    let all_passed = active_verdicts.iter().all(|v| v.passed);
    let avg_score =
        active_verdicts.iter().map(|v| v.score).sum::<f64>() / active_verdicts.len() as f64;
    let verdict_str = if all_passed {
        format!(
            "pass ({}/{} passed)",
            active_verdicts.len(),
            active_verdicts.len()
        )
    } else {
        let failed_count = active_verdicts.iter().filter(|v| !v.passed).count();
        format!("fail ({}/{} failed)", failed_count, active_verdicts.len())
    };

    (Some(verdict_str), Some(avg_score))
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
            sca_gate: Some("pass (scanner: cargo-audit)".to_string()),
            eval_verdict: Some("pass (2/2 passed)".to_string()),
            eval_score: Some(0.95),
            agent_role: Some("design_engineer".to_string()),
            model: Some("claude-3-7-sonnet".to_string()),
            model_tier: Some("fast".to_string()),
            cost_usd: Some(0.1420),
            bom_id: Some("bom-abc-123".to_string()),
            bom_digest: Some("sha256:digest-abc".to_string()),
            bom_signature: Some("sig-xyz".to_string()),
            bom_key_id: Some("pa-factory-ed25519-123".to_string()),
        };

        let formatted = meta.format_trailers();
        assert!(formatted.contains("X-PA-Task-ID: feat-auth-001"));
        assert!(formatted.contains("X-PA-Key-Results: KR-AUTH-01,KR-AUTH-02"));
        assert!(formatted.contains("X-PA-Design-Platforms: web,ios"));
        assert!(formatted.contains("X-PA-SCA-Gate: pass (scanner: cargo-audit)"));
        assert!(formatted.contains("X-PA-Eval-Verdict: pass (2/2 passed)"));
        assert!(formatted.contains("X-PA-Eval-Score: 0.95"));
        assert!(formatted.contains("X-PA-Model-Tier: fast"));
        assert!(formatted.contains("X-PA-BOM-ID: bom-abc-123"));
        assert!(formatted.contains("X-PA-BOM-Digest: sha256:digest-abc"));

        let commit_msg = stamp_commit_message("feat: add token rotation", &meta);
        let parsed = GitProvenanceMetadata::parse(&commit_msg);

        assert_eq!(parsed.task_id, "feat-auth-001");
        assert_eq!(parsed.objective_id.as_deref(), Some("OBJ-2026-Q4-SEC"));
        assert_eq!(parsed.bom_id.as_deref(), Some("bom-abc-123"));
        assert_eq!(parsed.bom_digest.as_deref(), Some("sha256:digest-abc"));
        assert_eq!(parsed.bom_signature.as_deref(), Some("sig-xyz"));
        assert_eq!(parsed.bom_key_id.as_deref(), Some("pa-factory-ed25519-123"));
        assert_eq!(parsed.kr_ids, vec!["KR-AUTH-01", "KR-AUTH-02"]);
        assert_eq!(parsed.design_gate.as_deref(), Some("passed"));
        assert_eq!(
            parsed.sca_gate.as_deref(),
            Some("pass (scanner: cargo-audit)")
        );
        assert_eq!(parsed.eval_verdict.as_deref(), Some("pass (2/2 passed)"));
        assert_eq!(parsed.eval_score, Some(0.95));
        assert_eq!(parsed.model_tier.as_deref(), Some("fast"));
        assert_eq!(parsed.cost_usd, Some(0.1420));
    }

    #[test]
    fn test_format_design_gate_trailer() {
        let mut report = crate::design::DesignGateReport::empty("git_only");
        assert_eq!(
            format_design_gate_trailer(&report),
            "tokens=pass, drift=pass, a11y=pass (0 violations), visual-diff=0.00%"
        );

        report.needs_design_review = true;
        assert_eq!(
            format_design_gate_trailer(&report),
            "tokens=pass, drift=pass, a11y=pass (0 violations), visual-diff=0.00%, needs-design-review"
        );

        report.is_compliant = false;
        report.violations.push(crate::design::DesignLintViolation {
            file: "app.tsx".to_string(),
            line: 10,
            rule: "raw_primitive_violation".to_string(),
            message: "raw button".to_string(),
            severity: "error".to_string(),
        });
        assert_eq!(
            format_design_gate_trailer(&report),
            "tokens=pass, drift=drift-detected, a11y=pass (0 violations), visual-diff=0.00%, needs-design-review"
        );
    }
}
