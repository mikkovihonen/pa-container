use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
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
}
