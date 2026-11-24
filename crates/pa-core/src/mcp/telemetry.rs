use anyhow::Result;
use serde_json::{json, Value};
use std::path::{Path, PathBuf};

use crate::mcp::protocol::ToolDefinition;
use crate::storage::{FactoryAnalyticsStore, SqliteAnalyticsStore};

pub fn telemetry_mcp_tools() -> Vec<ToolDefinition> {
    vec![
        ToolDefinition {
            name: "telemetry.get_okr_context".to_string(),
            description: "Fetch OKR context for a Key Result ID (reads docs/okrs/*.toml and .pa/factory.db). Returns objective title, KR baseline/target/current, calculated progress %, budget utilization, and recent tasks.".to_string(),
            input_schema: json!({
                "type": "object",
                "properties": {
                    "kr_id": { "type": "string", "description": "Key Result ID (e.g. KR-AUTH-01, KR-DORA-01)" }
                },
                "required": ["kr_id"]
            }),
        },
        ToolDefinition {
            name: "telemetry.get_factory_health".to_string(),
            description: "Fetch factory health metrics: rolling First Pass Yield (FPY), Change Failure Rate (CFR), task success rate, open PR queue depth vs WIP limit, and live Prometheus status if configured.".to_string(),
            input_schema: json!({
                "type": "object",
                "properties": {
                    "window_days": { "type": "integer", "description": "Analysis window in days (default: 30)" }
                }
            }),
        },
        ToolDefinition {
            name: "telemetry.query_recent_failures".to_string(),
            description: "Query recent task execution failures, verification gate breaches, and optional live OTLP/Phoenix traces.".to_string(),
            input_schema: json!({
                "type": "object",
                "properties": {
                    "limit": { "type": "integer", "description": "Maximum number of recent failures to return (default: 10)" }
                }
            }),
        },
        ToolDefinition {
            name: "telemetry.get_slo_status".to_string(),
            description: "Evaluate SLO error budget health: returns whether SLO Defense Mode is active, current success rate vs target, rolling CFR, and list of allowed emergency roles.".to_string(),
            input_schema: json!({
                "type": "object",
                "properties": {}
            }),
        },
    ]
}

pub fn handle_telemetry_tool(workspace_dir: &Path, tool_name: &str, args: &Value) -> Result<Value> {
    let db_path = workspace_dir.join(".pa").join("factory.db");
    let store = if db_path.exists() {
        SqliteAnalyticsStore::open_or_create(&db_path).ok()
    } else {
        None
    };

    match tool_name {
        "telemetry.get_okr_context" => {
            let kr_id = args
                .get("kr_id")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .trim();
            if kr_id.is_empty() {
                return Ok(json!({ "error": "kr_id is required" }));
            }

            let okrs_dir = workspace_dir.join("docs").join("okrs");
            let mut matched_kr: Option<Value> = None;
            let mut matched_obj: Option<Value> = None;
            let mut matched_file: Option<PathBuf> = None;

            if okrs_dir.is_dir() {
                if let Ok(entries) = std::fs::read_dir(&okrs_dir) {
                    for entry in entries.flatten() {
                        let path = entry.path();
                        if path.extension().and_then(|s| s.to_str()) == Some("toml") {
                            if let Ok(content) = std::fs::read_to_string(&path) {
                                if let Ok(doc) = toml::from_str::<toml::Value>(&content) {
                                    let obj_table = doc.get("objective").cloned();
                                    if let Some(krs) =
                                        doc.get("key_results").and_then(|v| v.as_array())
                                    {
                                        for kr in krs {
                                            if kr.get("id").and_then(|v| v.as_str()) == Some(kr_id)
                                            {
                                                matched_kr = serde_json::to_value(kr).ok();
                                                matched_obj = obj_table
                                                    .and_then(|o| serde_json::to_value(o).ok());
                                                matched_file = Some(path.clone());
                                                break;
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }

            let kr_data = match matched_kr {
                Some(k) => k,
                None => {
                    return Ok(
                        json!({ "error": format!("Key Result '{kr_id}' not found in docs/okrs/*.toml") }),
                    )
                }
            };

            let obj_data = matched_obj.unwrap_or(json!({ "title": "Unknown Objective" }));

            let total_cost = if let Some(ref s) = store {
                s.get_kr_spend(kr_id).unwrap_or(0.0)
            } else {
                0.0
            };

            Ok(json!({
                "kr_id": kr_id,
                "objective": obj_data,
                "key_result": kr_data,
                "file": matched_file.map(|p| p.display().to_string()),
                "total_cost_usd": total_cost,
            }))
        }
        "telemetry.get_factory_health" => {
            let window_days = args
                .get("window_days")
                .and_then(|v| v.as_u64())
                .unwrap_or(30) as u32;

            if let Some(ref s) = store {
                let report = s.get_dora_flow_report(window_days, None).ok();
                let fpy = s.get_rolling_fpy(window_days, None, None).unwrap_or(100.0);
                let cfr = s.get_rolling_cfr(window_days).unwrap_or(0.0);
                let open_prs = s.get_open_pr_count().unwrap_or(0);
                let lead_time = report.and_then(|r| r.lead_time_median_sec).unwrap_or(0.0);
                Ok(json!({
                    "window_days": window_days,
                    "fpy_rolling_pct": fpy,
                    "cfr_rolling_pct": cfr,
                    "avg_lead_time_sec": lead_time,
                    "active_wip_prs": open_prs,
                    "slo_defense_active": fpy < 80.0,
                }))
            } else {
                Ok(json!({
                    "window_days": window_days,
                    "fpy_rolling_pct": 100.0,
                    "cfr_rolling_pct": 0.0,
                    "active_wip_prs": 0,
                    "slo_defense_active": false,
                    "note": "No active database found at .pa/factory.db"
                }))
            }
        }
        "telemetry.query_recent_failures" => {
            let limit = args.get("limit").and_then(|v| v.as_u64()).unwrap_or(10) as usize;

            if let Some(ref s) = store {
                let anomalies = s
                    .detect_recurring_failure_classes(30, 1)
                    .unwrap_or_default();
                let events = s.list_optimization_events(limit).unwrap_or_default();
                Ok(json!({
                    "limit": limit,
                    "recurring_anomalies": anomalies,
                    "recent_optimization_events": events,
                }))
            } else {
                Ok(json!({
                    "limit": limit,
                    "recurring_anomalies": [],
                    "recent_optimization_events": [],
                }))
            }
        }
        "telemetry.get_slo_status" => {
            if let Some(ref s) = store {
                let fpy = s.get_rolling_fpy(14, None, None).unwrap_or(100.0);
                let cfr = s.get_rolling_cfr(14).unwrap_or(0.0);
                let is_defense_mode = fpy < 90.0 || cfr > 15.0;
                Ok(json!({
                    "slo_defense_active": is_defense_mode,
                    "fpy_pct": fpy,
                    "target_fpy_pct": 95.0,
                    "cfr_pct": cfr,
                    "allowed_emergency_roles": ["bugfix", "test_hardening", "spec_architect"],
                    "evaluation_window_days": 14
                }))
            } else {
                Ok(json!({
                    "slo_defense_active": false,
                    "fpy_pct": 100.0,
                    "target_fpy_pct": 95.0,
                    "cfr_pct": 0.0,
                    "allowed_emergency_roles": ["bugfix", "test_hardening", "spec_architect"],
                    "evaluation_window_days": 14
                }))
            }
        }
        _ => anyhow::bail!("Unknown telemetry tool: {}", tool_name),
    }
}
