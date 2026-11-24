use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use serde_json::json;
use sha2::{Digest, Sha256};
use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};

use crate::schema::OtlpTelemetrySpec;

static SPAN_COUNTER: AtomicU64 = AtomicU64::new(1);

pub fn generate_trace_id() -> String {
    let mut hasher = Sha256::new();
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0);
    hasher.update(now.to_le_bytes());
    hasher.update(std::process::id().to_le_bytes());
    hasher.update(SPAN_COUNTER.fetch_add(1, Ordering::Relaxed).to_le_bytes());
    let res = hasher.finalize();
    res[..16].iter().map(|b| format!("{:02x}", b)).collect()
}

pub fn generate_span_id() -> String {
    let mut hasher = Sha256::new();
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0);
    hasher.update(now.to_le_bytes());
    hasher.update(std::process::id().to_le_bytes());
    hasher.update(SPAN_COUNTER.fetch_add(1, Ordering::Relaxed).to_le_bytes());
    hasher.update(b"span");
    let res = hasher.finalize();
    res[..8].iter().map(|b| format!("{:02x}", b)).collect()
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct TaskContext {
    pub task_id: String,
    pub trace_id: String,
    pub span_id: String,
    #[serde(default)]
    pub parent_span_id: Option<String>,
    #[serde(default)]
    pub objective_id: Option<String>,
    #[serde(default)]
    pub kr_ids: Vec<String>,
    #[serde(default)]
    pub req_ids: Vec<String>,
    #[serde(default)]
    pub design_refs: Vec<String>,
    #[serde(default)]
    pub agent_role: Option<String>,
    #[serde(default)]
    pub model_profile: Option<String>,
    #[serde(default)]
    pub cost_usd: Option<f64>,
}

impl TaskContext {
    pub fn new(task_id: impl Into<String>) -> Self {
        Self {
            task_id: task_id.into(),
            trace_id: generate_trace_id(),
            span_id: generate_span_id(),
            parent_span_id: None,
            objective_id: None,
            kr_ids: Vec::new(),
            req_ids: Vec::new(),
            design_refs: Vec::new(),
            agent_role: None,
            model_profile: None,
            cost_usd: None,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, Default, PartialEq)]
pub struct ProxyBindings {
    #[serde(default)]
    pub ports: HashMap<String, TaskContext>,
}

impl ProxyBindings {
    pub fn new() -> Self {
        Self {
            ports: HashMap::new(),
        }
    }

    pub fn load(path: &Path) -> Result<Self> {
        if !path.is_file() {
            return Ok(Self::new());
        }
        let content = fs::read_to_string(path)
            .with_context(|| format!("Failed to read proxy bindings from {}", path.display()))?;
        let bindings: Self = serde_json::from_str(&content)
            .with_context(|| format!("Failed to parse proxy bindings from {}", path.display()))?;
        Ok(bindings)
    }

    pub fn save_atomic(&self, path: &Path) -> Result<()> {
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent)?;
        }
        let tmp_path = path.with_extension(format!("tmp.{}", std::process::id()));
        let json_data = serde_json::to_string_pretty(self)?;
        fs::write(&tmp_path, json_data)?;
        fs::rename(&tmp_path, path).with_context(|| {
            format!(
                "Failed to atomically rename proxy bindings to {}",
                path.display()
            )
        })?;
        Ok(())
    }

    pub fn get_by_port(&self, port: u16) -> Option<&TaskContext> {
        self.ports.get(&port.to_string())
    }

    pub fn set_for_port(&mut self, port: u16, ctx: TaskContext) {
        self.ports.insert(port.to_string(), ctx);
    }

    pub fn remove_port(&mut self, port: u16) -> Option<TaskContext> {
        self.ports.remove(&port.to_string())
    }
}

pub fn build_otlp_root_span_payload(
    task_ctx: &TaskContext,
    service_name: &str,
) -> serde_json::Value {
    let now_nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0);
    let start_nanos = now_nanos.to_string();
    let end_nanos = (now_nanos + 1_000_000).to_string();

    let mut attrs = vec![
        serde_json::json!({
            "key": "pa.task_id",
            "value": { "stringValue": task_ctx.task_id }
        }),
        serde_json::json!({
            "key": "openinference.span.kind",
            "value": { "stringValue": "CHAIN" }
        }),
    ];

    if let Some(role) = &task_ctx.agent_role {
        attrs.push(serde_json::json!({
            "key": "pa.agent_role",
            "value": { "stringValue": role }
        }));
    }
    if let Some(obj) = &task_ctx.objective_id {
        attrs.push(serde_json::json!({
            "key": "pa.objective_id",
            "value": { "stringValue": obj }
        }));
    }
    if !task_ctx.kr_ids.is_empty() {
        attrs.push(serde_json::json!({
            "key": "pa.kr_ids",
            "value": { "stringValue": task_ctx.kr_ids.join(",") }
        }));
    }
    if !task_ctx.req_ids.is_empty() {
        attrs.push(serde_json::json!({
            "key": "pa.req_ids",
            "value": { "stringValue": task_ctx.req_ids.join(",") }
        }));
    }
    if !task_ctx.design_refs.is_empty() {
        attrs.push(serde_json::json!({
            "key": "pa.design_refs",
            "value": { "stringValue": task_ctx.design_refs.join(",") }
        }));
    }
    if let Some(profile) = &task_ctx.model_profile {
        attrs.push(serde_json::json!({
            "key": "pa.model_profile",
            "value": { "stringValue": profile }
        }));
    }

    serde_json::json!({
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        {
                            "key": "service.name",
                            "value": { "stringValue": service_name }
                        },
                        {
                            "key": "pa.task_id",
                            "value": { "stringValue": task_ctx.task_id }
                        }
                    ]
                },
                "scopeSpans": [
                    {
                        "scope": {
                            "name": "pa.host.orchestrator",
                            "version": "2.0.0"
                        },
                        "spans": [
                            {
                                "traceId": task_ctx.trace_id,
                                "spanId": task_ctx.span_id,
                                "parentSpanId": task_ctx.parent_span_id.clone().unwrap_or_default(),
                                "name": "pa.task.run",
                                "kind": 1, // SPAN_KIND_INTERNAL
                                "startTimeUnixNano": start_nanos,
                                "endTimeUnixNano": end_nanos,
                                "attributes": attrs,
                                "status": { "code": 1 } // STATUS_CODE_OK
                            }
                        ]
                    }
                ]
            }
        ]
    })
}

pub fn append_local_event_jsonl(event: &serde_json::Value, fallback_file: &Path) -> Result<()> {
    if let Some(parent) = fallback_file.parent() {
        fs::create_dir_all(parent)?;
    }
    use std::io::Write;
    let mut file = fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(fallback_file)?;
    writeln!(file, "{}", serde_json::to_string(event)?)?;
    Ok(())
}

pub fn probe_otlp_endpoint(endpoint: &str) -> String {
    let probe = ureq::get(endpoint)
        .timeout(std::time::Duration::from_millis(800))
        .call();
    match probe {
        Ok(resp) => format!("Online (HTTP {})", resp.status()),
        Err(ureq::Error::Status(code, _)) => format!("Online (HTTP {})", code),
        Err(e) => format!("Offline ({})", e),
    }
}

pub fn emit_root_span(
    task_ctx: &TaskContext,
    config: &OtlpTelemetrySpec,
    fallback_dir: Option<&Path>,
) -> Result<()> {
    let payload = build_otlp_root_span_payload(task_ctx, "pa-container");
    let fallback_path = fallback_dir
        .map(|d| d.join("events.jsonl"))
        .unwrap_or_else(|| PathBuf::from(".pa/telemetry/events.jsonl"));

    if config.provider.to_lowercase() == "none" {
        append_local_event_jsonl(&payload, &fallback_path)?;
        return Ok(());
    }

    // Attempt HTTP POST export to OTLP collector endpoint (Phoenix / Langfuse / Generic)
    let post_result = ureq::post(&config.endpoint)
        .set("Content-Type", "application/json")
        .timeout(std::time::Duration::from_millis(
            config.batch_timeout_ms.max(500),
        ))
        .send_json(&payload);

    match post_result {
        Ok(_) => Ok(()),
        Err(e) => {
            // Graceful degradation: log warning and persist to local JSONL
            eprintln!(
                "[WARN] OTLP exporter to {} failed ({}). Degrading to local JSONL: {}",
                config.endpoint,
                e,
                fallback_path.display()
            );
            append_local_event_jsonl(&payload, &fallback_path)
        }
    }
}

pub fn build_otlp_eval_span_payload(
    task_ctx: &TaskContext,
    verdict: &crate::evals::EvalVerdict,
    service_name: &str,
) -> serde_json::Value {
    let now_nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0);
    let start_nanos = now_nanos.to_string();
    let end_nanos = (now_nanos + 1_000_000).to_string();
    let child_span_id = generate_span_id();

    let mut attrs = vec![
        serde_json::json!({
            "key": "pa.task_id",
            "value": { "stringValue": task_ctx.task_id }
        }),
        serde_json::json!({
            "key": "openinference.span.kind",
            "value": { "stringValue": "EVALUATOR" }
        }),
        serde_json::json!({
            "key": "pa.eval.rubric_id",
            "value": { "stringValue": verdict.rubric_id }
        }),
        serde_json::json!({
            "key": "pa.eval.stage",
            "value": { "stringValue": verdict.stage }
        }),
        serde_json::json!({
            "key": "pa.eval.judge_model",
            "value": { "stringValue": verdict.judge_model }
        }),
        serde_json::json!({
            "key": "pa.eval.score",
            "value": { "doubleValue": verdict.score }
        }),
        serde_json::json!({
            "key": "pa.eval.confidence",
            "value": { "doubleValue": verdict.confidence }
        }),
        serde_json::json!({
            "key": "pa.eval.passed",
            "value": { "boolValue": verdict.passed }
        }),
        serde_json::json!({
            "key": "pa.eval.escalated",
            "value": { "boolValue": verdict.escalated }
        }),
        serde_json::json!({
            "key": "pa.eval.cost_usd",
            "value": { "doubleValue": verdict.cost_usd }
        }),
    ];

    if let Some(ref rationale) = verdict.rationale {
        attrs.push(serde_json::json!({
            "key": "pa.eval.rationale",
            "value": { "stringValue": rationale }
        }));
    }

    serde_json::json!({
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        {
                            "key": "service.name",
                            "value": { "stringValue": service_name }
                        },
                        {
                            "key": "pa.task_id",
                            "value": { "stringValue": task_ctx.task_id }
                        }
                    ]
                },
                "scopeSpans": [
                    {
                        "scope": {
                            "name": "pa.eval.engine",
                            "version": "2.0.0"
                        },
                        "spans": [
                            {
                                "traceId": task_ctx.trace_id,
                                "spanId": child_span_id,
                                "parentSpanId": task_ctx.span_id,
                                "name": "pa.eval.run",
                                "kind": 1, // SPAN_KIND_INTERNAL
                                "startTimeUnixNano": start_nanos,
                                "endTimeUnixNano": end_nanos,
                                "attributes": attrs,
                                "status": {
                                    "code": if verdict.passed { 1 } else { 2 },
                                    "message": if verdict.passed { "OK" } else { "Eval Failed" }
                                }
                            }
                        ]
                    }
                ]
            }
        ]
    })
}

pub fn emit_eval_span(
    task_ctx: &TaskContext,
    verdict: &crate::evals::EvalVerdict,
    config: &OtlpTelemetrySpec,
    fallback_dir: Option<&Path>,
) -> Result<()> {
    let payload = build_otlp_eval_span_payload(task_ctx, verdict, "pa-container");
    let fallback_path = fallback_dir
        .map(|d| d.join("events.jsonl"))
        .unwrap_or_else(|| PathBuf::from(".pa/telemetry/events.jsonl"));

    if config.provider.to_lowercase() == "none" {
        append_local_event_jsonl(&payload, &fallback_path)?;
        return Ok(());
    }

    let post_result = ureq::post(&config.endpoint)
        .set("Content-Type", "application/json")
        .timeout(std::time::Duration::from_millis(
            config.batch_timeout_ms.max(500),
        ))
        .send_json(&payload);

    match post_result {
        Ok(_) => (),
        Err(e) => {
            eprintln!(
                "[WARN] OTLP eval span export to {} failed ({}). Degrading to local JSONL: {}",
                config.endpoint,
                e,
                fallback_path.display()
            );
            let _ = append_local_event_jsonl(&payload, &fallback_path);
        }
    }

    // Optional direct Phoenix REST evaluation export
    if config.provider.to_lowercase() == "phoenix" {
        let base_url = config.endpoint.trim_end_matches("/v1/traces");
        let eval_url = format!("{}/v1/evaluations", base_url);
        let eval_payload = serde_json::json!({
            "dataframe": {
                "name": verdict.rubric_id,
                "score": verdict.score,
                "label": if verdict.passed { "pass" } else { "fail" },
                "explanation": verdict.rationale.as_deref().unwrap_or(""),
                "trace_id": task_ctx.trace_id,
                "span_id": task_ctx.span_id,
            }
        });
        let _ = ureq::post(&eval_url)
            .set("Content-Type", "application/json")
            .timeout(std::time::Duration::from_millis(500))
            .send_json(&eval_payload);
    }

    Ok(())
}

pub fn build_otlp_traceability_span_payload(
    task_ctx: &TaskContext,
    report: &crate::traceability::TraceabilityReport,
    service_name: &str,
) -> serde_json::Value {
    let now_nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0);
    let start_nanos = now_nanos.to_string();
    let end_nanos = (now_nanos + 1_000_000).to_string();
    let child_span_id = generate_span_id();

    let mut attrs = vec![
        serde_json::json!({
            "key": "pa.task_id",
            "value": { "stringValue": task_ctx.task_id }
        }),
        serde_json::json!({
            "key": "openinference.span.kind",
            "value": { "stringValue": "GUARDRAIL" }
        }),
        serde_json::json!({
            "key": "pa.gate.type",
            "value": { "stringValue": "traceability" }
        }),
        serde_json::json!({
            "key": "pa.traceability.engine",
            "value": { "stringValue": report.engine }
        }),
        serde_json::json!({
            "key": "pa.traceability.total_requirements",
            "value": { "intValue": report.total_requirements as i64 }
        }),
        serde_json::json!({
            "key": "pa.traceability.covered_requirements",
            "value": { "intValue": report.covered_requirements as i64 }
        }),
        serde_json::json!({
            "key": "pa.traceability.coverage_pct",
            "value": { "doubleValue": report.coverage_pct }
        }),
        serde_json::json!({
            "key": "pa.traceability.is_compliant",
            "value": { "boolValue": report.is_compliant }
        }),
        serde_json::json!({
            "key": "pa.traceability.tests_passed",
            "value": { "intValue": report.tests_passed as i64 }
        }),
        serde_json::json!({
            "key": "pa.traceability.tests_failed",
            "value": { "intValue": report.tests_failed as i64 }
        }),
        serde_json::json!({
            "key": "pa.traceability.tests_unexecuted",
            "value": { "intValue": report.tests_unexecuted as i64 }
        }),
    ];

    if let Some(cov) = report.line_coverage_pct {
        attrs.push(serde_json::json!({
            "key": "pa.traceability.line_coverage_pct",
            "value": { "doubleValue": cov }
        }));
    }

    serde_json::json!({
        "resourceSpans": [{
            "resource": {
                "attributes": [{
                    "key": "service.name",
                    "value": { "stringValue": service_name }
                }]
            },
            "scopeSpans": [{
                "scope": {
                    "name": "pa.gate.traceability",
                    "version": "2.0.0"
                },
                "spans": [{
                    "traceId": task_ctx.trace_id,
                    "spanId": child_span_id,
                    "parentSpanId": task_ctx.span_id,
                    "name": "pa.gate.traceability",
                    "kind": 1,
                    "startTimeUnixNano": start_nanos,
                    "endTimeUnixNano": end_nanos,
                    "attributes": attrs,
                    "status": {
                        "code": if report.is_compliant { 1 } else { 2 },
                        "message": if report.is_compliant { "PASSED" } else { "FAILED" }
                    }
                }]
            }]
        }]
    })
}

pub fn emit_traceability_span(
    task_ctx: &TaskContext,
    report: &crate::traceability::TraceabilityReport,
    config: &OtlpTelemetrySpec,
    fallback_dir: Option<&Path>,
) -> Result<()> {
    let payload = build_otlp_traceability_span_payload(task_ctx, report, "pa-container");
    let fallback_path = fallback_dir
        .map(|d| d.join("events.jsonl"))
        .unwrap_or_else(|| PathBuf::from(".pa/telemetry/events.jsonl"));

    if config.provider.to_lowercase() == "none" {
        append_local_event_jsonl(&payload, &fallback_path)?;
        return Ok(());
    }

    let post_result = ureq::post(&config.endpoint)
        .set("Content-Type", "application/json")
        .timeout(std::time::Duration::from_millis(
            config.batch_timeout_ms.max(500),
        ))
        .send_json(&payload);

    match post_result {
        Ok(_) => Ok(()),
        Err(e) => {
            eprintln!(
                "[WARN] OTLP traceability span export to {} failed ({}). Degrading to local JSONL: {}",
                config.endpoint,
                e,
                fallback_path.display()
            );
            append_local_event_jsonl(&payload, &fallback_path)
        }
    }
}

pub fn build_otlp_design_span_payload(
    task_ctx: &TaskContext,
    report: &crate::design::DesignGateReport,
    service_name: &str,
) -> serde_json::Value {
    let now_nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0);
    let start_nanos = now_nanos.to_string();
    let end_nanos = (now_nanos + 1_000_000).to_string();
    let child_span_id = generate_span_id();

    let platforms_str = report
        .platform_results
        .keys()
        .cloned()
        .collect::<Vec<_>>()
        .join(",");
    let raw_primitive_violations = report
        .violations
        .iter()
        .filter(|v| v.rule == "raw_primitive_violation")
        .count();

    let attrs = vec![
        serde_json::json!({
            "key": "pa.task_id",
            "value": { "stringValue": task_ctx.task_id }
        }),
        serde_json::json!({
            "key": "openinference.span.kind",
            "value": { "stringValue": "GUARDRAIL" }
        }),
        serde_json::json!({
            "key": "pa.gate.type",
            "value": { "stringValue": "design_system" }
        }),
        serde_json::json!({
            "key": "pa.design.provider",
            "value": { "stringValue": report.provider }
        }),
        serde_json::json!({
            "key": "pa.design.platforms",
            "value": { "stringValue": platforms_str }
        }),
        serde_json::json!({
            "key": "pa.design.is_compliant",
            "value": { "boolValue": report.is_compliant }
        }),
        serde_json::json!({
            "key": "pa.design.needs_design_review",
            "value": { "boolValue": report.needs_design_review }
        }),
        serde_json::json!({
            "key": "pa.design.new_components_count",
            "value": { "intValue": report.new_components.len() as i64 }
        }),
        serde_json::json!({
            "key": "pa.design.raw_primitive_violations",
            "value": { "intValue": raw_primitive_violations as i64 }
        }),
        serde_json::json!({
            "key": "pa.design.total_violations",
            "value": { "intValue": report.violations.len() as i64 }
        }),
        serde_json::json!({
            "key": "pa.design.a11y_violations",
            "value": { "intValue": report.a11y_violations.len() as i64 }
        }),
        serde_json::json!({
            "key": "pa.design.failed_snapshots",
            "value": { "intValue": report.visual_diff_failures.len() as i64 }
        }),
        serde_json::json!({
            "key": "pa.design.visual_diff_pct",
            "value": { "doubleValue": report.visual_diff_pct }
        }),
    ];

    serde_json::json!({
        "resourceSpans": [{
            "resource": {
                "attributes": [{
                    "key": "service.name",
                    "value": { "stringValue": service_name }
                }]
            },
            "scopeSpans": [{
                "scope": {
                    "name": "pa.gate.design_system",
                    "version": "2.0.0"
                },
                "spans": [{
                    "traceId": task_ctx.trace_id,
                    "spanId": child_span_id,
                    "parentSpanId": task_ctx.span_id,
                    "name": "pa.gate.design_system",
                    "kind": 1,
                    "startTimeUnixNano": start_nanos,
                    "endTimeUnixNano": end_nanos,
                    "attributes": attrs,
                    "status": {
                        "code": if report.is_compliant { 1 } else { 2 },
                        "message": if report.is_compliant {
                            if report.needs_design_review { "NEEDS_DESIGN_REVIEW" } else { "PASSED" }
                        } else {
                            "FAILED"
                        }
                    }
                }]
            }]
        }]
    })
}

pub fn emit_design_gate_span(
    task_ctx: &TaskContext,
    report: &crate::design::DesignGateReport,
    config: &OtlpTelemetrySpec,
    fallback_dir: Option<&Path>,
) -> Result<()> {
    let payload = build_otlp_design_span_payload(task_ctx, report, "pa-container");
    let fallback_path = fallback_dir
        .map(|d| d.join("events.jsonl"))
        .unwrap_or_else(|| PathBuf::from(".pa/telemetry/events.jsonl"));

    if config.provider.to_lowercase() == "none" {
        append_local_event_jsonl(&payload, &fallback_path)?;
        return Ok(());
    }

    let post_result = ureq::post(&config.endpoint)
        .set("Content-Type", "application/json")
        .timeout(std::time::Duration::from_millis(
            config.batch_timeout_ms.max(500),
        ))
        .send_json(&payload);

    match post_result {
        Ok(_) => Ok(()),
        Err(e) => {
            eprintln!(
                "[WARN] OTLP design gate span export to {} failed ({}). Degrading to local JSONL: {}",
                config.endpoint,
                e,
                fallback_path.display()
            );
            append_local_event_jsonl(&payload, &fallback_path)
        }
    }
}

pub fn build_otlp_sca_span_payload(
    task_ctx: &TaskContext,
    report: &crate::sca::ScaGateReport,
    service_name: &str,
) -> serde_json::Value {
    let now_nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0);
    let span_id = format!("{:016x}", rand::random::<u64>());
    let parent_span_id = task_ctx.parent_span_id.clone().unwrap_or_default();

    json!({
        "resourceSpans": [{
            "resource": {
                "attributes": [
                    { "key": "service.name", "value": { "stringValue": service_name } }
                ]
            },
            "scopeSpans": [{
                "scope": { "name": "pa-container.sca", "version": "2.0.0" },
                "spans": [{
                    "traceId": task_ctx.trace_id,
                    "spanId": span_id,
                    "parentSpanId": parent_span_id,
                    "name": "gate.sca",
                    "kind": 1,
                    "startTimeUnixNano": now_nanos.saturating_sub(10_000_000).to_string(),
                    "endTimeUnixNano": now_nanos.to_string(),
                    "attributes": [
                        { "key": "pa.task_id", "value": { "stringValue": task_ctx.task_id } },
                        { "key": "pa.gate.type", "value": { "stringValue": "sca" } },
                        { "key": "pa.sca.scanner", "value": { "stringValue": report.scanner } },
                        { "key": "pa.sca.is_compliant", "value": { "boolValue": report.is_compliant } },
                        { "key": "pa.sca.vulnerabilities_found", "value": { "intValue": report.vulnerabilities_found as i64 } },
                        { "key": "pa.sca.blocking_count", "value": { "intValue": report.blocking_vulnerabilities.len() as i64 } },
                        { "key": "pa.sca.status", "value": { "stringValue": report.status } }
                    ],
                    "status": {
                        "code": if report.is_compliant { 1 } else { 2 },
                        "message": if report.is_compliant { "PASSED" } else { "FAILED" }
                    }
                }]
            }]
        }]
    })
}

pub fn emit_sca_gate_span(
    task_ctx: &TaskContext,
    report: &crate::sca::ScaGateReport,
    config: &OtlpTelemetrySpec,
    fallback_dir: Option<&Path>,
) -> Result<()> {
    let payload = build_otlp_sca_span_payload(task_ctx, report, "pa-container");
    let fallback_path = fallback_dir
        .map(|d| d.join("events.jsonl"))
        .unwrap_or_else(|| PathBuf::from(".pa/telemetry/events.jsonl"));

    if config.provider.to_lowercase() == "none" {
        append_local_event_jsonl(&payload, &fallback_path)?;
        return Ok(());
    }

    let post_result = ureq::post(&config.endpoint)
        .set("Content-Type", "application/json")
        .timeout(std::time::Duration::from_millis(
            config.batch_timeout_ms.max(500),
        ))
        .send_json(&payload);

    match post_result {
        Ok(_) => Ok(()),
        Err(e) => {
            eprintln!(
                "[WARN] OTLP SCA gate span export to {} failed ({}). Degrading to local JSONL: {}",
                config.endpoint,
                e,
                fallback_path.display()
            );
            append_local_event_jsonl(&payload, &fallback_path)
        }
    }
}

pub fn build_otlp_escalation_span_payload(
    task_ctx: &TaskContext,
    trigger: &str,
    previous_tier: &str,
    promoted_tier: &str,
    reason: &str,
    service_name: &str,
) -> serde_json::Value {
    let now_nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0);
    let span_id = format!("{:016x}", rand::random::<u64>());
    let parent_span_id = task_ctx.parent_span_id.clone().unwrap_or_default();

    json!({
        "resourceSpans": [{
            "resource": {
                "attributes": [
                    { "key": "service.name", "value": { "stringValue": service_name } }
                ]
            },
            "scopeSpans": [{
                "scope": { "name": "pa-container.governance", "version": "2.0.0" },
                "spans": [{
                    "traceId": task_ctx.trace_id,
                    "spanId": span_id,
                    "parentSpanId": parent_span_id,
                    "name": "governance.escalation",
                    "kind": 1,
                    "startTimeUnixNano": now_nanos.saturating_sub(5_000_000).to_string(),
                    "endTimeUnixNano": now_nanos.to_string(),
                    "attributes": [
                        { "key": "pa.task_id", "value": { "stringValue": task_ctx.task_id } },
                        { "key": "pa.escalation.trigger", "value": { "stringValue": trigger } },
                        { "key": "pa.escalation.previous_tier", "value": { "stringValue": previous_tier } },
                        { "key": "pa.escalation.promoted_tier", "value": { "stringValue": promoted_tier } },
                        { "key": "pa.escalation.reason", "value": { "stringValue": reason } }
                    ],
                    "status": {
                        "code": 1,
                        "message": "PROMOTED"
                    }
                }]
            }]
        }]
    })
}

pub fn emit_escalation_span(
    task_ctx: &TaskContext,
    trigger: &str,
    previous_tier: &str,
    promoted_tier: &str,
    reason: &str,
    config: &OtlpTelemetrySpec,
    fallback_dir: Option<&Path>,
) -> Result<()> {
    let payload = build_otlp_escalation_span_payload(
        task_ctx,
        trigger,
        previous_tier,
        promoted_tier,
        reason,
        "pa-container",
    );
    let fallback_path = fallback_dir
        .map(|d| d.join("events.jsonl"))
        .unwrap_or_else(|| PathBuf::from(".pa/telemetry/events.jsonl"));

    if config.provider.to_lowercase() == "none" {
        append_local_event_jsonl(&payload, &fallback_path)?;
        return Ok(());
    }

    let post_result = ureq::post(&config.endpoint)
        .set("Content-Type", "application/json")
        .timeout(std::time::Duration::from_millis(
            config.batch_timeout_ms.max(500),
        ))
        .send_json(&payload);

    match post_result {
        Ok(_) => Ok(()),
        Err(e) => {
            eprintln!(
                "[WARN] OTLP escalation span export to {} failed ({}). Degrading to local JSONL: {}",
                config.endpoint,
                e,
                fallback_path.display()
            );
            append_local_event_jsonl(&payload, &fallback_path)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn test_task_context_ids() {
        let ctx = TaskContext::new("task-42");
        assert_eq!(ctx.task_id, "task-42");
        assert_eq!(ctx.trace_id.len(), 32);
        assert_eq!(ctx.span_id.len(), 16);
    }

    #[test]
    fn test_proxy_bindings_persistence() {
        let td = tempdir().unwrap();
        let path = td.path().join("proxy-bindings.json");

        let mut bindings = ProxyBindings::new();
        let mut ctx = TaskContext::new("feat-01");
        ctx.objective_id = Some("OBJ-01".to_string());
        ctx.kr_ids = vec!["KR-01".to_string()];
        ctx.agent_role = Some("design_engineer".to_string());

        bindings.set_for_port(8081, ctx.clone());
        bindings.save_atomic(&path).unwrap();

        let loaded = ProxyBindings::load(&path).unwrap();
        let port_ctx = loaded.get_by_port(8081).unwrap();
        assert_eq!(port_ctx.task_id, "feat-01");
        assert_eq!(port_ctx.objective_id.as_deref(), Some("OBJ-01"));
        assert_eq!(port_ctx.agent_role.as_deref(), Some("design_engineer"));
    }

    #[test]
    fn test_build_otlp_payload() {
        let mut ctx = TaskContext::new("feat-02");
        ctx.objective_id = Some("OBJ-SEC".to_string());
        ctx.kr_ids = vec!["KR-AUTH".to_string()];
        let payload = build_otlp_root_span_payload(&ctx, "test-service");

        let spans = payload["resourceSpans"][0]["scopeSpans"][0]["spans"]
            .as_array()
            .unwrap();
        assert_eq!(spans.len(), 1);
        assert_eq!(spans[0]["name"], "pa.task.run");
        assert_eq!(spans[0]["traceId"], ctx.trace_id);
    }

    #[test]
    fn test_emit_root_span_provider_none() {
        let td = tempdir().unwrap();
        let ctx = TaskContext::new("feat-none");
        let spec = OtlpTelemetrySpec {
            provider: "none".to_string(),
            ..OtlpTelemetrySpec::default()
        };

        emit_root_span(&ctx, &spec, Some(td.path())).unwrap();
        let events_file = td.path().join("events.jsonl");
        assert!(events_file.is_file());
        let content = fs::read_to_string(events_file).unwrap();
        assert!(content.contains("pa.task.run"));
        assert!(content.contains(&ctx.trace_id));
    }

    #[test]
    fn test_build_and_emit_eval_span() {
        let td = tempdir().unwrap();
        let ctx = TaskContext::new("feat-eval-task");
        let verdict = crate::evals::EvalVerdict {
            rubric_id: "spec_adherence".to_string(),
            stage: "cascade".to_string(),
            judge_model: "qwen2.5-coder-32b".to_string(),
            score: 0.95,
            confidence: 0.90,
            passed: true,
            escalated: false,
            checklist_results: Vec::new(),
            rationale: Some("All requirements met".to_string()),
            cost_usd: 0.002,
            skipped: false,
            skip_reason: None,
        };

        let payload = build_otlp_eval_span_payload(&ctx, &verdict, "test-service");
        let span = &payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0];
        assert_eq!(span["name"], "pa.eval.run");
        assert_eq!(span["traceId"], ctx.trace_id);
        assert_eq!(span["parentSpanId"], ctx.span_id);

        let spec = OtlpTelemetrySpec {
            provider: "none".to_string(),
            ..OtlpTelemetrySpec::default()
        };
        emit_eval_span(&ctx, &verdict, &spec, Some(td.path())).unwrap();
        let events_file = td.path().join("events.jsonl");
        assert!(events_file.is_file());
        let content = fs::read_to_string(events_file).unwrap();
        assert!(content.contains("pa.eval.run"));
        assert!(content.contains("spec_adherence"));
        assert!(content.contains("qwen2.5-coder-32b"));
    }
}
