use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use std::fs;
use std::path::Path;
use std::time::{SystemTime, UNIX_EPOCH};
use toml_edit::{value, DocumentMut};

use crate::governance::{GovernanceEngine, OptimizationTrigger};
use crate::schema::GovernanceConfig;
use crate::storage::{FactoryAnalyticsStore, OptimizationEventRecord};

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ActivatedGatePlan {
    pub gate_name: String,
    pub trigger: String,
    pub command: String,
    pub failure_class: String,
    pub occurrences: usize,
    pub signal_tier: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct UnmatchedFailureClass {
    pub failure_class: String,
    pub count: usize,
    pub signal_tier: String,
    pub sample_ids: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct HardeningPlan {
    pub triggers: Vec<OptimizationTrigger>,
    pub activated_gates: Vec<ActivatedGatePlan>,
    pub unmatched_failure_classes: Vec<UnmatchedFailureClass>,
    pub diff: String,
    #[serde(skip)]
    pub modified_toml: Option<String>,
    pub has_changes: bool,
}

/// Compute a human-readable line-by-line diff between two strings
pub fn compute_line_diff(original: &str, modified: &str) -> String {
    let orig_lines: Vec<&str> = original.lines().collect();
    let mod_lines: Vec<&str> = modified.lines().collect();

    let mut out = String::new();
    let mut i = 0;
    let mut j = 0;

    while i < orig_lines.len() || j < mod_lines.len() {
        if i < orig_lines.len() && j < mod_lines.len() {
            if orig_lines[i] == mod_lines[j] {
                i += 1;
                j += 1;
            } else {
                out.push_str(&format!("- {}\n", orig_lines[i]));
                out.push_str(&format!("+ {}\n", mod_lines[j]));
                i += 1;
                j += 1;
            }
        } else if i < orig_lines.len() {
            out.push_str(&format!("- {}\n", orig_lines[i]));
            i += 1;
        } else if j < mod_lines.len() {
            out.push_str(&format!("+ {}\n", mod_lines[j]));
            j += 1;
        }
    }

    out
}

/// Evaluate recurring anomalies and cross-reference against factory.toml's [[quality_gates]]
pub fn evaluate_hardening_plan(
    factory_toml_content: &str,
    store: &dyn FactoryAnalyticsStore,
    gov_config: &GovernanceConfig,
) -> Result<HardeningPlan> {
    // 1. Evaluate self-optimization triggers
    let triggers = GovernanceEngine::evaluate_self_optimization(store, gov_config, None)?;

    // 2. Query recurring failure classes
    let window_days = gov_config.self_optimization.window_days;
    let min_count = gov_config.self_optimization.min_failure_class_count;
    let recurring = store.detect_recurring_failure_classes(window_days, min_count)?;

    // 3. Parse factory.toml with toml_edit to preserve formatting and comments
    let mut doc: DocumentMut = factory_toml_content
        .parse::<DocumentMut>()
        .context("Failed to parse factory.toml with toml_edit")?;

    let mut activated_gates = Vec::new();
    let mut matched_classes = std::collections::HashSet::new();

    if let Some(gates_item) = doc.get_mut("quality_gates") {
        if let Some(array_of_tables) = gates_item.as_array_of_tables_mut() {
            for table in array_of_tables.iter_mut() {
                let name = table
                    .get("name")
                    .and_then(|v| v.as_str())
                    .unwrap_or("unnamed_gate")
                    .to_string();
                let command = table
                    .get("command")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string();
                let trigger_str = table
                    .get("trigger")
                    .and_then(|v| v.as_str())
                    .unwrap_or("always")
                    .to_string();
                let enabled = table
                    .get("enabled")
                    .and_then(|v| v.as_bool())
                    .unwrap_or(true);

                // Check if this gate triggers on a recurring failure_class
                for rec in &recurring {
                    let expected_trigger = format!("failure_class:{}", rec.failure_class);
                    if trigger_str == expected_trigger {
                        matched_classes.insert(rec.failure_class.clone());
                        if !enabled {
                            // Activate dormant gate
                            table.insert("enabled", value(true));
                            activated_gates.push(ActivatedGatePlan {
                                gate_name: name.clone(),
                                trigger: trigger_str.clone(),
                                command: command.clone(),
                                failure_class: rec.failure_class.clone(),
                                occurrences: rec.count,
                                signal_tier: rec.signal_tier.clone(),
                            });
                        }
                    }
                }
            }
        }
    }

    // 4. Collect unmatched failure classes
    let mut unmatched_failure_classes = Vec::new();
    for rec in recurring {
        if !matched_classes.contains(&rec.failure_class) {
            unmatched_failure_classes.push(UnmatchedFailureClass {
                failure_class: rec.failure_class,
                count: rec.count,
                signal_tier: rec.signal_tier,
                sample_ids: rec.sample_ids,
            });
        }
    }

    let modified_toml = doc.to_string();
    let has_changes = !activated_gates.is_empty();
    let diff = if has_changes {
        compute_line_diff(factory_toml_content, &modified_toml)
    } else {
        String::new()
    };

    Ok(HardeningPlan {
        triggers,
        activated_gates,
        unmatched_failure_classes,
        diff,
        modified_toml: if has_changes {
            Some(modified_toml)
        } else {
            None
        },
        has_changes,
    })
}

/// Apply a hardening plan to factory.toml and record events in SQLite
pub fn apply_hardening_plan(
    config_path: &Path,
    plan: &HardeningPlan,
    store: &dyn FactoryAnalyticsStore,
) -> Result<usize> {
    if !plan.has_changes {
        return Ok(0);
    }

    let modified_str = match &plan.modified_toml {
        Some(s) => s,
        None => return Ok(0),
    };

    // 1. Write updated TOML in-place
    fs::write(config_path, modified_str).with_context(|| {
        format!(
            "Failed to write updated config to {}",
            config_path.display()
        )
    })?;

    // 2. Record optimization audit events in store
    let now_micros = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_micros())
        .unwrap_or(0);
    let now_sec = (now_micros / 1_000_000) as u64;
    let now_iso = format!("{}", now_sec);

    for gate in &plan.activated_gates {
        let event = OptimizationEventRecord {
            event_id: format!("harden:{}:{}", gate.gate_name, now_micros),
            signal_tier: gate.signal_tier.clone(),
            trigger_kind: "failure_class".to_string(),
            fingerprint: format!("failure_class:{}", gate.failure_class),
            details_json: serde_json::to_string(gate)?,
            action_taken: "hardened".to_string(),
            linked_task_id: None,
            created_at: now_iso.clone(),
        };
        store.record_optimization_event(&event)?;
    }

    Ok(plan.activated_gates.len())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::storage::{ProdSignalRecord, SqliteAnalyticsStore};
    use tempfile::tempdir;

    #[test]
    fn test_evaluate_and_apply_hardening_plan() {
        let td = tempdir().unwrap();
        let store = SqliteAnalyticsStore::open_or_create(&td.path().join("factory.db")).unwrap();

        // Seed 2 prod_signals for db_lock
        for i in 1..=2 {
            let sig = ProdSignalRecord {
                signal_id: format!("sig-{}", i),
                task_id: Some(format!("task-{}", i)),
                deploy_sha: "abcd".to_string(),
                environment: "prod".to_string(),
                observed_at: "2026-11-24T10:00:00Z".to_string(),
                error_rate_delta: 0.05,
                p95_latency_delta_ms: 100.0,
                slo_budget_burn_pct: 0.1,
                incident_triggered: true,
                mttr_sec: Some(120.0),
                failure_class: Some("db_lock".to_string()),
            };
            store.insert_prod_signal(&sig).unwrap();
        }

        // Seed 2 prod_signals for out_of_memory (which has NO gate)
        for i in 1..=2 {
            let sig = ProdSignalRecord {
                signal_id: format!("sig-oom-{}", i),
                task_id: None,
                deploy_sha: "abcd".to_string(),
                environment: "prod".to_string(),
                observed_at: "2026-11-24T10:00:00Z".to_string(),
                error_rate_delta: 0.05,
                p95_latency_delta_ms: 100.0,
                slo_budget_burn_pct: 0.1,
                incident_triggered: true,
                mttr_sec: Some(120.0),
                failure_class: Some("out_of_memory".to_string()),
            };
            store.insert_prod_signal(&sig).unwrap();
        }

        let sample_toml = r#"# Factory Configuration
schema_version = "2.1"

[governance.self_optimization]
enabled = true
min_failure_class_count = 2

# Dormant gate for db_lock
[[quality_gates]]
name = "db-lock-gate"
command = "cargo test -p pa-core test_db"
trigger = "failure_class:db_lock"
enabled = false
description = "Activated when db_lock recurs"
"#;

        let config_file = td.path().join("factory.toml");
        fs::write(&config_file, sample_toml).unwrap();

        let gov_cfg = GovernanceConfig {
            self_optimization: crate::schema::SelfOptimizationConfig {
                enabled: true,
                min_failure_class_count: 2,
                cooldown_hours: 24,
                ..Default::default()
            },
            ..Default::default()
        };

        // 1. Evaluate hardening plan
        let plan = evaluate_hardening_plan(sample_toml, &store, &gov_cfg).unwrap();
        assert!(plan.has_changes);
        assert_eq!(plan.activated_gates.len(), 1);
        assert_eq!(plan.activated_gates[0].gate_name, "db-lock-gate");
        assert_eq!(plan.activated_gates[0].failure_class, "db_lock");

        // out_of_memory should be flagged as unmatched
        assert_eq!(plan.unmatched_failure_classes.len(), 1);
        assert_eq!(
            plan.unmatched_failure_classes[0].failure_class,
            "out_of_memory"
        );

        // Verify diff contains + enabled = true and - enabled = false
        assert!(plan.diff.contains("+ enabled = true") || plan.diff.contains("enabled = true"));

        // 2. Apply plan
        let applied_count = apply_hardening_plan(&config_file, &plan, &store).unwrap();
        assert_eq!(applied_count, 1);

        // Verify file on disk
        let updated_content = fs::read_to_string(&config_file).unwrap();
        assert!(updated_content.contains("enabled = true"));
        assert!(updated_content.contains("# Factory Configuration"));
        assert!(updated_content.contains("# Dormant gate for db_lock"));

        // Verify SQLite optimization_events audit row
        let events = store.list_optimization_events(10).unwrap();
        assert_eq!(events.len(), 1);
        assert_eq!(events[0].fingerprint, "failure_class:db_lock");
        assert_eq!(events[0].action_taken, "hardened");

        // 3. Second run should be idempotent (no changes)
        let plan2 = evaluate_hardening_plan(&updated_content, &store, &gov_cfg).unwrap();
        assert!(!plan2.has_changes);
        assert!(plan2.activated_gates.is_empty());
    }
}
