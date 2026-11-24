use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use std::fs::File;
use std::io::{BufRead, BufReader, Seek, SeekFrom};
use std::path::PathBuf;
use std::time::{SystemTime, UNIX_EPOCH};

use crate::git_trailers::GitProvenanceMetadata;
use crate::okr::OkrStore;
use crate::schema::{TelemetryConfig, TelemetryMetricsSpec, TelemetryVcsSpec};
use crate::storage::{
    parse_timestamp_epoch_sec, FactoryAnalyticsStore, KrSnapshotRecord, VcsOutcomeRecord,
};

// -----------------------------------------------------------------------------
// 1. Proxy JSONL Ingestor
// -----------------------------------------------------------------------------

pub struct JsonlCollector {
    pub path: PathBuf,
}

impl JsonlCollector {
    pub fn new(path: impl Into<PathBuf>) -> Self {
        Self { path: path.into() }
    }

    /// Ingests events from the JSONL file starting from the cursor offset in storage.
    /// Supports OTLP resourceSpans format as well as flat JSON event lines.
    /// Updates task token usage and cost in the storage, and advances the cursor.
    pub fn ingest(&self, store: &dyn FactoryAnalyticsStore) -> Result<usize> {
        if !self.path.exists() || !self.path.is_file() {
            return Ok(0);
        }

        let cursor_key = "jsonl:events";
        let start_offset: u64 = store
            .get_sync_cursor(cursor_key)?
            .and_then(|s| s.parse().ok())
            .unwrap_or(0);

        let mut file = File::open(&self.path).with_context(|| {
            format!("Failed to open JSONL events file: {}", self.path.display())
        })?;

        let metadata = file.metadata()?;
        let file_len = metadata.len();

        let seek_pos = if start_offset > file_len {
            0
        } else {
            start_offset
        };

        file.seek(SeekFrom::Start(seek_pos))?;
        let mut reader = BufReader::new(file);

        let mut count = 0;
        let mut current_offset = seek_pos;
        let mut line = String::new();

        while reader.read_line(&mut line)? > 0 {
            let bytes_read = line.len() as u64;
            let trimmed = line.trim();

            if !trimmed.is_empty() {
                if let Ok(val) = serde_json::from_str::<serde_json::Value>(trimmed) {
                    if let Some((task_id, prompt_tokens, completion_tokens, cost_usd)) =
                        Self::parse_event_metrics(&val)
                    {
                        if !task_id.is_empty() {
                            let _ = store.update_task_usage(
                                &task_id,
                                prompt_tokens,
                                completion_tokens,
                                cost_usd,
                            );
                            count += 1;
                        }
                    }
                }
            }

            current_offset += bytes_read;
            line.clear();
        }

        store.set_sync_cursor(cursor_key, &current_offset.to_string())?;
        Ok(count)
    }

    fn parse_event_metrics(val: &serde_json::Value) -> Option<(String, u64, u64, f64)> {
        // Flat JSON detection
        if let Some(task_id) = val.get("task_id").and_then(|v| v.as_str()) {
            let prompt_tokens = val
                .get("prompt_tokens")
                .and_then(|v| v.as_u64())
                .unwrap_or(0);
            let completion_tokens = val
                .get("completion_tokens")
                .and_then(|v| v.as_u64())
                .unwrap_or(0);
            let cost_usd = val.get("cost_usd").and_then(|v| v.as_f64()).unwrap_or(
                (prompt_tokens as f64 * 0.000003) + (completion_tokens as f64 * 0.000015),
            );
            return Some((
                task_id.to_string(),
                prompt_tokens,
                completion_tokens,
                cost_usd,
            ));
        }

        // OTLP resourceSpans detection
        if let Some(resource_spans) = val.get("resourceSpans").and_then(|v| v.as_array()) {
            for rs in resource_spans {
                let mut task_id = String::new();
                let mut prompt_tokens = 0u64;
                let mut completion_tokens = 0u64;
                let mut cost_usd = 0.0f64;
                let mut found_task = false;

                // Check resource attributes
                if let Some(attrs) = rs
                    .get("resource")
                    .and_then(|r| r.get("attributes"))
                    .and_then(|a| a.as_array())
                {
                    for attr in attrs {
                        let key = attr.get("key").and_then(|k| k.as_str()).unwrap_or("");
                        if key == "pa.task_id" || key == "task_id" {
                            if let Some(s) = attr
                                .get("value")
                                .and_then(|v| v.get("stringValue"))
                                .and_then(|v| v.as_str())
                            {
                                task_id = s.to_string();
                                found_task = true;
                            }
                        }
                    }
                }

                // Check scopeSpans and spans
                if let Some(scope_spans) = rs.get("scopeSpans").and_then(|s| s.as_array()) {
                    for ss in scope_spans {
                        if let Some(spans) = ss.get("spans").and_then(|s| s.as_array()) {
                            for span in spans {
                                if let Some(attrs) =
                                    span.get("attributes").and_then(|a| a.as_array())
                                {
                                    for attr in attrs {
                                        let key =
                                            attr.get("key").and_then(|k| k.as_str()).unwrap_or("");
                                        if !found_task && (key == "pa.task_id" || key == "task_id")
                                        {
                                            if let Some(s) = attr
                                                .get("value")
                                                .and_then(|v| v.get("stringValue"))
                                                .and_then(|v| v.as_str())
                                            {
                                                task_id = s.to_string();
                                                found_task = true;
                                            }
                                        } else if key == "llm.token_count.prompt"
                                            || key == "gen_ai.usage.input_tokens"
                                            || key == "prompt_tokens"
                                        {
                                            if let Some(n) = attr
                                                .get("value")
                                                .and_then(|v| v.get("intValue"))
                                                .and_then(|v| v.as_i64())
                                            {
                                                prompt_tokens += n.max(0) as u64;
                                            }
                                        } else if key == "llm.token_count.completion"
                                            || key == "gen_ai.usage.output_tokens"
                                            || key == "completion_tokens"
                                        {
                                            if let Some(n) = attr
                                                .get("value")
                                                .and_then(|v| v.get("intValue"))
                                                .and_then(|v| v.as_i64())
                                            {
                                                completion_tokens += n.max(0) as u64;
                                            }
                                        } else if key == "pa.cost_usd" || key == "cost_usd" {
                                            if let Some(f) = attr
                                                .get("value")
                                                .and_then(|v| v.get("doubleValue"))
                                                .and_then(|v| v.as_f64())
                                            {
                                                cost_usd += f;
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }

                if found_task && !task_id.is_empty() {
                    if cost_usd <= 0.0 && (prompt_tokens > 0 || completion_tokens > 0) {
                        cost_usd = (prompt_tokens as f64 * 0.000003)
                            + (completion_tokens as f64 * 0.000015);
                    }
                    return Some((task_id, prompt_tokens, completion_tokens, cost_usd));
                }
            }
        }

        None
    }
}

// -----------------------------------------------------------------------------
// 2. VCS Collectors
// -----------------------------------------------------------------------------

pub trait VcsCollector: Send + Sync {
    fn poll_prs(&self, since: Option<&str>, lookback_days: u32) -> Result<Vec<VcsOutcomeRecord>>;
}

pub struct NoopVcsCollector;

impl VcsCollector for NoopVcsCollector {
    fn poll_prs(&self, _since: Option<&str>, _lookback_days: u32) -> Result<Vec<VcsOutcomeRecord>> {
        Ok(Vec::new())
    }
}

pub struct GitHubCollector {
    pub repo: String,
    pub api_base_url: String,
    pub token: Option<String>,
}

impl VcsCollector for GitHubCollector {
    fn poll_prs(&self, _since: Option<&str>, _lookback_days: u32) -> Result<Vec<VcsOutcomeRecord>> {
        if self.repo.is_empty() {
            return Ok(Vec::new());
        }

        let token = match &self.token {
            Some(t) if !t.is_empty() => t.clone(),
            _ => {
                eprintln!(
                    "[WARN] GitHub VCS collector: No authentication token configured or found. Skipping remote VCS sync for {}.",
                    self.repo
                );
                return Ok(Vec::new());
            }
        };

        let base = self.api_base_url.trim_end_matches('/');
        let url = format!(
            "{}/repos/{}/pulls?state=all&sort=updated&direction=desc&per_page=100",
            base, self.repo
        );

        let req = ureq::get(&url)
            .set("Accept", "application/vnd.github.v3+json")
            .set("User-Agent", "pa-container-software-factory")
            .set("Authorization", &format!("Bearer {}", token));

        let resp = match req.call() {
            Ok(r) => r,
            Err(e) => {
                eprintln!(
                    "[WARN] GitHub VCS collector request to {} failed: {}. Continuing with degraded mode.",
                    url, e
                );
                return Ok(Vec::new());
            }
        };

        let items: serde_json::Value = match resp.into_json() {
            Ok(j) => j,
            Err(e) => {
                eprintln!("[WARN] Failed to parse GitHub API response as JSON: {}", e);
                return Ok(Vec::new());
            }
        };

        let arr = match items.as_array() {
            Some(a) => a,
            None => return Ok(Vec::new()),
        };

        let now_iso = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_secs().to_string())
            .unwrap_or_default();

        let mut outcomes = Vec::new();

        for item in arr {
            let pr_number = item.get("number").and_then(|v| v.as_u64()).unwrap_or(0);
            let pr_id = format!("gh-{}-{}", self.repo.replace('/', "-"), pr_number);
            let state_raw = item.get("state").and_then(|v| v.as_str()).unwrap_or("open");
            let merged_at = item
                .get("merged_at")
                .and_then(|v| v.as_str())
                .map(|s| s.to_string());
            let state = if merged_at.is_some() {
                "merged".to_string()
            } else {
                state_raw.to_string()
            };

            let opened_at = item
                .get("created_at")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();

            let title = item.get("title").and_then(|v| v.as_str()).unwrap_or("");
            let body = item.get("body").and_then(|v| v.as_str()).unwrap_or("");
            let reverted = title.to_lowercase().contains("revert");

            // Extract Task ID from PR body or title
            let meta = GitProvenanceMetadata::parse(body);
            let task_id = if !meta.task_id.is_empty() {
                Some(meta.task_id)
            } else {
                None
            };

            // Calculate lead time in seconds if merged
            let lead_time_sec = if let Some(ref m_at) = merged_at {
                if let (Some(m_sec), Some(o_sec)) = (
                    parse_timestamp_epoch_sec(m_at),
                    parse_timestamp_epoch_sec(&opened_at),
                ) {
                    if m_sec >= o_sec {
                        Some((m_sec - o_sec) as f64)
                    } else {
                        None
                    }
                } else {
                    None
                }
            } else {
                None
            };

            // Optionally probe reviews for CHANGES_REQUESTED
            let mut review_rounds = 0u32;
            let reviews_url = format!("{}/repos/{}/pulls/{}/reviews", base, self.repo, pr_number);
            if let Ok(rev_resp) = ureq::get(&reviews_url)
                .set("Accept", "application/vnd.github.v3+json")
                .set("User-Agent", "pa-container-software-factory")
                .set("Authorization", &format!("Bearer {}", token))
                .call()
            {
                if let Ok(rev_json) = rev_resp.into_json::<serde_json::Value>() {
                    if let Some(rev_arr) = rev_json.as_array() {
                        for rev in rev_arr {
                            if let Some(st) = rev.get("state").and_then(|s| s.as_str()) {
                                if st == "CHANGES_REQUESTED" {
                                    review_rounds += 1;
                                }
                            }
                        }
                    }
                }
            }

            outcomes.push(VcsOutcomeRecord {
                pr_id,
                task_id,
                repo: self.repo.clone(),
                pr_number,
                state,
                opened_at,
                first_review_at: None,
                merged_at,
                human_review_rounds: review_rounds,
                human_commits_added: 0,
                ci_runs_count: 1,
                ci_failed_first_run: false,
                reverted,
                lead_time_sec,
                synced_at: now_iso.clone(),
            });
        }

        Ok(outcomes)
    }
}

pub struct GitLabCollector {
    pub repo: String,
    pub api_base_url: String,
    pub token: Option<String>,
}

impl VcsCollector for GitLabCollector {
    fn poll_prs(&self, _since: Option<&str>, _lookback_days: u32) -> Result<Vec<VcsOutcomeRecord>> {
        if self.repo.is_empty() || self.token.is_none() {
            return Ok(Vec::new());
        }
        // Graceful degradation for GitLab
        Ok(Vec::new())
    }
}

pub struct ForgejoCollector {
    pub repo: String,
    pub api_base_url: String,
    pub token: Option<String>,
}

impl VcsCollector for ForgejoCollector {
    fn poll_prs(&self, _since: Option<&str>, _lookback_days: u32) -> Result<Vec<VcsOutcomeRecord>> {
        if self.repo.is_empty() || self.token.is_none() {
            return Ok(Vec::new());
        }
        // Graceful degradation for Forgejo/Gitea
        Ok(Vec::new())
    }
}

pub fn create_vcs_collector(spec: &TelemetryVcsSpec) -> Box<dyn VcsCollector> {
    match spec.provider.to_lowercase().as_str() {
        "github" => {
            let token = spec.resolve_token().map(|t| t.to_string());
            let repo = spec.repo.clone().unwrap_or_default();
            let api_base_url = spec
                .api_base_url
                .clone()
                .unwrap_or_else(|| "https://api.github.com".to_string());
            Box::new(GitHubCollector {
                repo,
                api_base_url,
                token,
            })
        }
        "gitlab" => {
            let token = spec.resolve_token().map(|t| t.to_string());
            let repo = spec.repo.clone().unwrap_or_default();
            let api_base_url = spec
                .api_base_url
                .clone()
                .unwrap_or_else(|| "https://gitlab.com".to_string());
            Box::new(GitLabCollector {
                repo,
                api_base_url,
                token,
            })
        }
        "forgejo" | "gitea" => {
            let token = spec.resolve_token().map(|t| t.to_string());
            let repo = spec.repo.clone().unwrap_or_default();
            let api_base_url = spec
                .api_base_url
                .clone()
                .unwrap_or_else(|| "https://codeberg.org".to_string());
            Box::new(ForgejoCollector {
                repo,
                api_base_url,
                token,
            })
        }
        _ => Box::new(NoopVcsCollector),
    }
}

// -----------------------------------------------------------------------------
// 3. Metrics Collectors
// -----------------------------------------------------------------------------

pub trait MetricsCollector: Send + Sync {
    fn collect_metrics(&self, store: &OkrStore) -> Result<Vec<KrSnapshotRecord>>;
}

pub struct NoopMetricsCollector;

impl MetricsCollector for NoopMetricsCollector {
    fn collect_metrics(&self, _store: &OkrStore) -> Result<Vec<KrSnapshotRecord>> {
        Ok(Vec::new())
    }
}

pub struct PrometheusCollector {
    pub endpoint: String,
    pub token: Option<String>,
}

impl MetricsCollector for PrometheusCollector {
    fn collect_metrics(&self, store: &OkrStore) -> Result<Vec<KrSnapshotRecord>> {
        if self.endpoint.is_empty() || self.endpoint == "none" {
            return Ok(Vec::new());
        }

        let base = self.endpoint.trim_end_matches('/');
        let url = format!("{}/api/v1/query", base);
        let now_sec = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_secs().to_string())
            .unwrap_or_default();

        let mut snapshots = Vec::new();

        for kr in store.key_results.values() {
            if kr.metric_query.is_empty() {
                continue;
            }

            let mut req = ureq::get(&url)
                .query("query", &kr.metric_query)
                .set("User-Agent", "pa-container-software-factory");

            if let Some(ref t) = self.token {
                req = req.set("Authorization", &format!("Bearer {}", t));
            }

            let resp = match req.call() {
                Ok(r) => r,
                Err(e) => {
                    eprintln!(
                        "[WARN] Prometheus metric query for KR '{}' failed: {}. Continuing.",
                        kr.id, e
                    );
                    continue;
                }
            };

            let body: serde_json::Value = match resp.into_json() {
                Ok(j) => j,
                Err(_) => continue,
            };

            // Parse Prometheus instant vector value: data.result[0].value[1]
            let val_opt = body
                .get("data")
                .and_then(|d| d.get("result"))
                .and_then(|r| r.as_array())
                .and_then(|arr| arr.first())
                .and_then(|first| first.get("value"))
                .and_then(|v| v.as_array())
                .and_then(|arr| arr.get(1))
                .and_then(|v| v.as_str())
                .and_then(|s| s.parse::<f64>().ok());

            if let Some(val) = val_opt {
                let progress_pct = compute_kr_progress(val, kr.baseline, kr.target);
                snapshots.push(KrSnapshotRecord {
                    snapshot_id: format!("{}-{}", kr.id, now_sec),
                    kr_id: kr.id.clone(),
                    observed_at: now_sec.clone(),
                    value: val,
                    progress_pct,
                    latest_deploy_sha: None,
                });
            }
        }

        Ok(snapshots)
    }
}

pub struct ManualMetricsCollector {
    pub kr_id: String,
    pub value: f64,
}

impl MetricsCollector for ManualMetricsCollector {
    fn collect_metrics(&self, store: &OkrStore) -> Result<Vec<KrSnapshotRecord>> {
        let now_sec = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_secs().to_string())
            .unwrap_or_default();

        let progress_pct = if let Some(kr) = store.key_results.get(&self.kr_id) {
            compute_kr_progress(self.value, kr.baseline, kr.target)
        } else {
            0.0
        };

        Ok(vec![KrSnapshotRecord {
            snapshot_id: format!("{}-{}", self.kr_id, now_sec),
            kr_id: self.kr_id.clone(),
            observed_at: now_sec,
            value: self.value,
            progress_pct,
            latest_deploy_sha: None,
        }])
    }
}

pub fn create_metrics_collector(spec: &TelemetryMetricsSpec) -> Box<dyn MetricsCollector> {
    match spec.provider.to_lowercase().as_str() {
        "prometheus" | "grafana" => {
            let endpoint = spec
                .endpoint
                .clone()
                .unwrap_or_else(|| "http://127.0.0.1:9090".to_string());
            let token = spec.resolve_token().map(|t| t.to_string());
            Box::new(PrometheusCollector { endpoint, token })
        }
        _ => Box::new(NoopMetricsCollector),
    }
}

pub fn compute_kr_progress(value: f64, baseline: f64, target: f64) -> f64 {
    let span = target - baseline;
    if span.abs() < f64::EPSILON {
        return 100.0;
    }
    if target > baseline {
        ((value - baseline) / span * 100.0).max(0.0)
    } else {
        ((baseline - value) / (baseline - target) * 100.0).max(0.0)
    }
}

// -----------------------------------------------------------------------------
// 4. Telemetry Sync Orchestrator
// -----------------------------------------------------------------------------

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
pub struct SyncReport {
    pub jsonl_events_ingested: usize,
    pub vcs_outcomes_synced: usize,
    pub kr_snapshots_recorded: usize,
    pub warnings: Vec<String>,
}

pub fn sync_telemetry(
    config: &TelemetryConfig,
    analytics_store: &dyn FactoryAnalyticsStore,
    okr_store: Option<&OkrStore>,
    source_filter: Option<&str>,
    manual_kr: Option<(&str, f64)>,
) -> Result<SyncReport> {
    let mut report = SyncReport::default();
    let filter = source_filter.unwrap_or("all").to_lowercase();
    let sync_all = filter == "all" || filter.is_empty();

    // 1. Ingest JSONL events
    if sync_all || filter == "jsonl" {
        let jsonl_collector = JsonlCollector::new(&config.sync.jsonl_path);
        match jsonl_collector.ingest(analytics_store) {
            Ok(count) => {
                report.jsonl_events_ingested = count;
            }
            Err(e) => {
                let msg = format!("JSONL ingestion warning: {}", e);
                eprintln!("[WARN] {}", msg);
                report.warnings.push(msg);
            }
        }
    }

    // 2. Sync VCS outcomes
    if sync_all || filter == "vcs" {
        let vcs_collector = create_vcs_collector(&config.vcs);
        let cursor = analytics_store.get_sync_cursor("vcs:last_sync")?;
        match vcs_collector.poll_prs(cursor.as_deref(), config.vcs.lookback_days) {
            Ok(outcomes) => {
                for outcome in &outcomes {
                    analytics_store.upsert_vcs_outcome(outcome)?;
                }
                report.vcs_outcomes_synced = outcomes.len();

                let now_sec = SystemTime::now()
                    .duration_since(UNIX_EPOCH)
                    .map(|d| d.as_secs().to_string())
                    .unwrap_or_default();
                analytics_store.set_sync_cursor("vcs:last_sync", &now_sec)?;
            }
            Err(e) => {
                let msg = format!("VCS sync warning: {}", e);
                eprintln!("[WARN] {}", msg);
                report.warnings.push(msg);
            }
        }
    }

    // 3. Sync OKR / Metrics
    if sync_all || filter == "okr" || manual_kr.is_some() {
        let empty_store = OkrStore::new();
        let store_ref = okr_store.unwrap_or(&empty_store);

        if let Some((kr_id, val)) = manual_kr {
            let manual_collector = ManualMetricsCollector {
                kr_id: kr_id.to_string(),
                value: val,
            };
            if let Ok(snapshots) = manual_collector.collect_metrics(store_ref) {
                for sn in &snapshots {
                    analytics_store.insert_kr_snapshot(sn)?;
                }
                report.kr_snapshots_recorded += snapshots.len();
            }
        } else {
            let metrics_collector = create_metrics_collector(&config.metrics);
            match metrics_collector.collect_metrics(store_ref) {
                Ok(snapshots) => {
                    for sn in &snapshots {
                        analytics_store.insert_kr_snapshot(sn)?;
                    }
                    report.kr_snapshots_recorded += snapshots.len();

                    let now_sec = SystemTime::now()
                        .duration_since(UNIX_EPOCH)
                        .map(|d| d.as_secs().to_string())
                        .unwrap_or_default();
                    analytics_store.set_sync_cursor("okr:last_sync", &now_sec)?;
                }
                Err(e) => {
                    let msg = format!("Metrics sync warning: {}", e);
                    eprintln!("[WARN] {}", msg);
                    report.warnings.push(msg);
                }
            }
        }
    }

    Ok(report)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::okr::{KeyResultSpec, ObjectiveSpec};
    use crate::storage::SqliteAnalyticsStore;
    use tempfile::tempdir;

    #[test]
    fn test_compute_kr_progress() {
        // Increase direction
        assert!((compute_kr_progress(50.0, 0.0, 100.0) - 50.0).abs() < 1e-6);
        assert!((compute_kr_progress(100.0, 0.0, 100.0) - 100.0).abs() < 1e-6);
        assert!((compute_kr_progress(-10.0, 0.0, 100.0) - 0.0).abs() < 1e-6);

        // Decrease direction
        assert!((compute_kr_progress(50.0, 100.0, 0.0) - 50.0).abs() < 1e-6);
        assert!((compute_kr_progress(0.0, 100.0, 0.0) - 100.0).abs() < 1e-6);
        assert!((compute_kr_progress(120.0, 100.0, 0.0) - 0.0).abs() < 1e-6);
    }

    #[test]
    fn test_jsonl_collector_ingest_and_cursor() {
        let td = tempdir().unwrap();
        let db_path = td.path().join("factory.db");
        let jsonl_path = td.path().join("events.jsonl");

        let store = SqliteAnalyticsStore::open_or_create(&db_path).unwrap();

        // Write first batch of events
        let event1 = serde_json::json!({
            "task_id": "task-alpha-1",
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "cost_usd": 0.001
        });
        let event2 = serde_json::json!({
            "task_id": "task-alpha-2",
            "prompt_tokens": 200,
            "completion_tokens": 100,
            "cost_usd": 0.002
        });

        std::fs::write(&jsonl_path, format!("{}\n{}\n", event1, event2)).unwrap();

        let collector = JsonlCollector::new(&jsonl_path);
        let ingested = collector.ingest(&store).unwrap();
        assert_eq!(ingested, 2);

        // Verify tasks table updated
        let t1 = store.get_task("task-alpha-1").unwrap().unwrap();
        assert_eq!(t1.prompt_tokens, 100);
        assert_eq!(t1.completion_tokens, 50);

        // Ingest again without new lines -> cursor should result in 0 new ingested
        let ingested_again = collector.ingest(&store).unwrap();
        assert_eq!(ingested_again, 0);

        // Append line
        use std::io::Write;
        let mut file = std::fs::OpenOptions::new()
            .append(true)
            .open(&jsonl_path)
            .unwrap();
        let event3 = serde_json::json!({
            "task_id": "task-alpha-1",
            "prompt_tokens": 50,
            "completion_tokens": 25,
            "cost_usd": 0.0005
        });
        writeln!(file, "{}", event3).unwrap();

        let ingested_third = collector.ingest(&store).unwrap();
        assert_eq!(ingested_third, 1);

        let t1_updated = store.get_task("task-alpha-1").unwrap().unwrap();
        assert_eq!(t1_updated.prompt_tokens, 150);
        assert_eq!(t1_updated.completion_tokens, 75);
    }

    #[test]
    fn test_sync_telemetry_graceful_degradation() {
        let td = tempdir().unwrap();
        let db_path = td.path().join("factory.db");
        let store = SqliteAnalyticsStore::open_or_create(&db_path).unwrap();

        let mut config = TelemetryConfig::default();
        config.vcs.provider = "github".to_string();
        config.vcs.repo = Some("owner/nonexistent-repo".to_string());
        config.vcs.keyring_token = Some("NONEXISTENT_KEY".to_string());

        let mut okr_store = OkrStore::new();
        okr_store.objectives.insert(
            "OBJ-1".to_string(),
            ObjectiveSpec {
                id: "OBJ-1".to_string(),
                title: "Test".to_string(),
                owner: "team".to_string(),
                budget_usd: 1000.0,
            },
        );
        okr_store.key_results.insert(
            "KR-1".to_string(),
            KeyResultSpec {
                id: "KR-1".to_string(),
                title: "Reduce latency".to_string(),
                metric_query: "up".to_string(),
                baseline: 200.0,
                target: 50.0,
                current: 200.0,
                budget_usd: 500.0,
                linked_reqs: vec![],
            },
        );

        // Sync with manual KR
        let report = sync_telemetry(
            &config,
            &store,
            Some(&okr_store),
            Some("all"),
            Some(("KR-1", 125.0)),
        )
        .unwrap();

        assert_eq!(report.kr_snapshots_recorded, 1);
        let snapshots = store.list_kr_snapshots(Some("KR-1"), 10).unwrap();
        assert_eq!(snapshots.len(), 1);
        assert!((snapshots[0].progress_pct - 50.0).abs() < 1e-6);
    }
}
