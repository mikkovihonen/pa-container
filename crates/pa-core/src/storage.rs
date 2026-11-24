use anyhow::{Context, Result};
use rusqlite::{params, Connection};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::time::{SystemTime, UNIX_EPOCH};

use crate::telemetry::TaskContext;
use crate::traceability::TraceabilityReport;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct AnalyticsSummary {
    pub total_tasks: usize,
    pub verified_tasks: usize,
    pub failed_tasks: usize,
    pub total_cost_usd: f64,
    pub avg_traceability_pct: f64,
    pub kr_spends: HashMap<String, f64>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct TaskRecord {
    pub task_id: String,
    pub trace_id: String,
    pub objective_id: Option<String>,
    pub agent_role: Option<String>,
    pub model: Option<String>,
    pub cost_usd: Option<f64>,
    pub status: String,
    pub created_at: String,
    pub prompt_tokens: u64,
    pub completion_tokens: u64,
    pub kr_ids: Vec<String>,
    pub req_ids: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct VcsOutcomeRecord {
    pub pr_id: String,
    pub task_id: Option<String>,
    pub repo: String,
    pub pr_number: u64,
    pub state: String, // "open", "merged", "closed"
    pub opened_at: String,
    pub first_review_at: Option<String>,
    pub merged_at: Option<String>,
    pub human_review_rounds: u32,
    pub human_commits_added: u32,
    pub ci_runs_count: u32,
    pub ci_failed_first_run: bool,
    pub reverted: bool,
    pub lead_time_sec: Option<f64>,
    pub synced_at: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ProdSignalRecord {
    pub signal_id: String,
    pub task_id: Option<String>,
    pub deploy_sha: String,
    pub environment: String,
    pub observed_at: String,
    pub error_rate_delta: f64,
    pub p95_latency_delta_ms: f64,
    pub slo_budget_burn_pct: f64,
    pub incident_triggered: bool,
    pub mttr_sec: Option<f64>,
    pub failure_class: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct KrSnapshotRecord {
    pub snapshot_id: String,
    pub kr_id: String,
    pub observed_at: String,
    pub value: f64,
    pub progress_pct: f64,
    pub latest_deploy_sha: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct SyncCursorRecord {
    pub source_key: String,
    pub cursor_val: String,
    pub updated_at: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct DoraFlowReport {
    pub window_days: u32,
    pub group_by: Option<String>,
    pub lead_time_median_sec: Option<f64>,
    pub lead_time_p95_sec: Option<f64>,
    pub deployment_frequency_per_day: f64,
    pub change_failure_rate: f64,
    pub mttr_avg_sec: Option<f64>,
    pub first_pass_yield: f64,
    pub flow_efficiency: f64,
    pub open_pr_queue_depth: usize,
    pub cost_per_merged_pr: Option<f64>,
    pub cost_per_first_pass_pr: Option<f64>,
    pub total_merged_prs: usize,
    pub groups: HashMap<String, DoraFlowGroupMetrics>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct DoraFlowGroupMetrics {
    pub group_key: String,
    pub merged_prs: usize,
    pub lead_time_median_sec: Option<f64>,
    pub change_failure_rate: f64,
    pub first_pass_yield: f64,
    pub total_cost_usd: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct BomRecord {
    pub bom_id: String,
    pub task_id: Option<String>,
    pub trace_id: Option<String>,
    pub commit_sha: Option<String>,
    pub created_at: String,
    pub bom_digest: String,
    pub signing_key_id: String,
    pub signature_b64: String,
    pub target_name: String,
    pub target_version: String,
    pub cyclonedx_path: String,
    pub slsa_path: String,
    pub canonical_path: String,
    pub substrate_type: String,
    pub substrate_fingerprint: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct BomArtifactRecord {
    pub artifact_id: String,
    pub bom_id: String,
    pub name: String,
    pub path: String,
    pub sha256: String,
    pub sha512: String,
    pub size_bytes: u64,
    pub mime_type: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct BomMaterialRecord {
    pub material_id: String,
    pub bom_id: String,
    pub plane: String,
    pub category: String,
    pub name: String,
    pub version: Option<String>,
    pub hash: String,
    pub details_json: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct QueuedTask {
    pub task_id: String,
    pub role: String,
    pub req_ids: Vec<String>,
    pub kr_ids: Vec<String>,
    pub priority: i32,
    pub status: String,
    pub attempt_count: u32,
    pub model_tier: String,
    pub assigned_uid: Option<u32>,
    pub proxy_port: Option<u16>,
    pub lease_expires_at: Option<i64>,
    pub failure_context: Option<String>,
    pub created_at: String,
    pub updated_at: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct WorkerLeaseRecord {
    pub slot_id: usize,
    pub uid: u32,
    pub proxy_port: u16,
    pub task_id: Option<String>,
    pub leased_at: Option<i64>,
    pub expires_at: Option<i64>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct EvalResultRecord {
    pub eval_id: String,
    pub task_id: String,
    pub trace_id: String,
    pub rubric_id: String,
    pub stage: String,
    pub judge_model: String,
    pub score: f64,
    pub confidence: f64,
    pub passed: bool,
    pub escalated: bool,
    pub rationale: Option<String>,
    pub checklist_json: String,
    pub cost_usd: f64,
    pub evaluated_at: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct RubricSummaryStat {
    pub count: usize,
    pub passed: usize,
    pub mean_score: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ModelSummaryStat {
    pub count: usize,
    pub passed: usize,
    pub mean_score: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct EvalSummaryReport {
    pub total_evals: usize,
    pub passed_count: usize,
    pub pass_rate: f64,
    pub mean_score: f64,
    pub mean_confidence: f64,
    pub escalation_rate: f64,
    pub total_cost_usd: f64,
    pub by_rubric: HashMap<String, RubricSummaryStat>,
    pub by_model: HashMap<String, ModelSummaryStat>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct RequirementLinkRecord {
    pub id: String,
    pub task_id: Option<String>,
    pub req_id: String,
    pub engine: String,
    pub impl_covered: bool,
    pub test_covered: bool,
    pub test_passed: bool,
    pub line_coverage_pct: Option<f64>,
    pub verified_at: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct DesignGateResultRecord {
    pub result_id: String,
    pub task_id: Option<String>,
    pub platform: String,
    pub token_violations: usize,
    pub raw_primitive_violations: usize,
    pub new_components_count: usize,
    pub needs_design_review: bool,
    pub a11y_violations: usize,
    pub visual_diff_pct: f64,
    pub status: String,
    pub created_at: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct OptimizationEventRecord {
    pub event_id: String,
    pub signal_tier: String,
    pub trigger_kind: String,
    pub fingerprint: String,
    pub details_json: String,
    pub action_taken: String,
    pub linked_task_id: Option<String>,
    pub created_at: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct RecurringFailureClassRecord {
    pub failure_class: String,
    pub count: usize,
    pub signal_tier: String,
    pub sample_ids: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ScaGateRecord {
    pub result_id: String,
    pub task_id: Option<String>,
    pub scanner: String,
    pub is_compliant: bool,
    pub vulnerabilities_found: usize,
    pub blocking_count: usize,
    pub summary: String,
    pub created_at: String,
}

pub trait FactoryAnalyticsStore: Send + Sync {
    fn record_task(&self, task_ctx: &TaskContext, status: &str) -> Result<()>;
    fn record_traceability(&self, task_id: &str, report: &TraceabilityReport) -> Result<()>;
    fn record_design_gate_report(
        &self,
        task_id: Option<&str>,
        report: &crate::design::DesignGateReport,
    ) -> Result<()>;
    fn get_task_design_gate_results(&self, task_id: &str) -> Result<Vec<DesignGateResultRecord>>;
    fn record_sca_gate_report(
        &self,
        task_id: Option<&str>,
        report: &crate::sca::ScaGateReport,
    ) -> Result<()>;
    fn get_sca_gate_report(&self, task_id: &str) -> Result<Option<ScaGateRecord>>;
    fn insert_requirement_links(
        &self,
        task_id: Option<&str>,
        engine: &str,
        report: &TraceabilityReport,
    ) -> Result<()>;
    fn get_requirement_links(&self, req_id: &str) -> Result<Vec<RequirementLinkRecord>>;
    fn get_task_requirement_links(&self, task_id: &str) -> Result<Vec<RequirementLinkRecord>>;
    fn record_vcs_outcome(&self, task_id: &str, commit_sha: &str, valid: bool) -> Result<()>;
    fn get_task(&self, task_id: &str) -> Result<Option<TaskRecord>>;
    fn list_tasks(&self, limit: usize) -> Result<Vec<TaskRecord>>;
    fn get_kr_spend(&self, kr_id: &str) -> Result<f64>;
    fn get_recent_success_rate(&self, limit: usize) -> Result<(usize, usize, f64)>;
    fn get_analytics_summary(&self) -> Result<AnalyticsSummary>;

    // Extended VCS, Signals, OKRs, and DORA/Flow capabilities
    fn upsert_vcs_outcome(&self, record: &VcsOutcomeRecord) -> Result<()>;
    fn insert_prod_signal(&self, record: &ProdSignalRecord) -> Result<()>;
    fn insert_kr_snapshot(&self, record: &KrSnapshotRecord) -> Result<()>;
    fn get_sync_cursor(&self, source_key: &str) -> Result<Option<String>>;
    fn set_sync_cursor(&self, source_key: &str, cursor_val: &str) -> Result<()>;
    fn get_open_pr_count(&self) -> Result<usize>;
    fn get_rolling_fpy(
        &self,
        window_days: u32,
        role: Option<&str>,
        model: Option<&str>,
    ) -> Result<f64>;
    fn get_rolling_cfr(&self, window_days: u32) -> Result<f64>;
    fn get_dora_flow_report(
        &self,
        window_days: u32,
        group_by: Option<&str>,
    ) -> Result<DoraFlowReport>;
    fn list_vcs_outcomes(&self, limit: usize) -> Result<Vec<VcsOutcomeRecord>>;
    fn list_kr_snapshots(&self, kr_id: Option<&str>, limit: usize)
        -> Result<Vec<KrSnapshotRecord>>;
    fn update_task_usage(
        &self,
        task_id: &str,
        prompt_tokens: u64,
        completion_tokens: u64,
        cost_usd: f64,
    ) -> Result<()>;

    // BOM capabilities
    fn record_bom(
        &self,
        bom: &crate::bom::FactoryBom,
        cdx_path: &Path,
        slsa_path: &Path,
        canonical_path: &Path,
    ) -> Result<()>;
    fn get_bom(&self, bom_id: &str) -> Result<Option<BomRecord>>;
    fn list_boms(&self, limit: usize) -> Result<Vec<BomRecord>>;
    fn get_bom_by_commit(&self, commit_sha: &str) -> Result<Option<BomRecord>>;
    fn get_bom_materials(&self, bom_id: &str) -> Result<Vec<BomMaterialRecord>>;
    fn get_bom_artifacts(&self, bom_id: &str) -> Result<Vec<BomArtifactRecord>>;

    // Work queue & supervisor lease capabilities
    fn enqueue_task(&self, task: &QueuedTask) -> Result<()>;
    fn get_queued_task(&self, task_id: &str) -> Result<Option<QueuedTask>>;
    fn list_queued_tasks(&self, status: Option<&str>, limit: usize) -> Result<Vec<QueuedTask>>;
    fn peek_next_task(
        &self,
        allowed_roles: &[String],
        skip_roles: &[String],
    ) -> Result<Option<QueuedTask>>;
    fn claim_task_lease(
        &self,
        task_id: &str,
        slot_id: usize,
        uid: u32,
        proxy_port: u16,
        lease_duration_sec: u64,
    ) -> Result<bool>;
    fn release_task_lease(&self, slot_id: usize) -> Result<()>;
    fn update_queued_task_status(
        &self,
        task_id: &str,
        status: &str,
        failure_context: Option<&str>,
    ) -> Result<()>;
    fn update_queued_task_attempt(
        &self,
        task_id: &str,
        attempt_count: u32,
        model_tier: &str,
        failure_context: Option<&str>,
    ) -> Result<()>;
    fn reclaim_expired_leases(&self) -> Result<Vec<String>>;
    fn list_worker_leases(&self) -> Result<Vec<WorkerLeaseRecord>>;
    fn init_worker_slots(
        &self,
        max_concurrent: usize,
        uid_start: u32,
        port_start: u16,
    ) -> Result<()>;
    fn get_model_tier_stats(
        &self,
        role: Option<&str>,
        model_tier: &str,
    ) -> Result<(usize, f64, f64)>;

    // Evals capabilities
    fn insert_eval_result(&self, record: &EvalResultRecord) -> Result<()>;
    fn get_task_evals(&self, task_id: &str) -> Result<Vec<EvalResultRecord>>;
    fn get_rolling_eval_score(
        &self,
        window_days: u32,
        rubric_id: Option<&str>,
        model: Option<&str>,
    ) -> Result<f64>;
    fn get_eval_summary(&self, window_days: u32) -> Result<EvalSummaryReport>;

    // Self-optimization and anomaly capabilities
    fn record_optimization_event(&self, record: &OptimizationEventRecord) -> Result<()>;
    fn has_recent_optimization_event(&self, fingerprint: &str, cooldown_hours: u32)
        -> Result<bool>;
    fn list_optimization_events(&self, limit: usize) -> Result<Vec<OptimizationEventRecord>>;
    fn detect_recurring_failure_classes(
        &self,
        window_days: u32,
        min_count: usize,
    ) -> Result<Vec<RecurringFailureClassRecord>>;
}

pub struct SqliteAnalyticsStore {
    conn: Mutex<Connection>,
    path: PathBuf,
}

impl SqliteAnalyticsStore {
    pub fn open_or_create(db_path: &Path) -> Result<Self> {
        if let Some(parent) = db_path.parent() {
            fs::create_dir_all(parent).with_context(|| {
                format!("Failed to create database directory: {}", parent.display())
            })?;
        }

        let conn = Connection::open(db_path)
            .with_context(|| format!("Failed to open SQLite database: {}", db_path.display()))?;

        // Initialize WAL mode and fast synchronous settings, followed by canonical table schema
        conn.execute_batch(
            "PRAGMA journal_mode=WAL;
             PRAGMA synchronous=NORMAL;
             PRAGMA foreign_keys=ON;

             CREATE TABLE IF NOT EXISTS tasks (
                 task_id TEXT PRIMARY KEY,
                 trace_id TEXT NOT NULL,
                 objective_id TEXT,
                 agent_role TEXT,
                 model TEXT,
                 cost_usd REAL,
                 status TEXT NOT NULL,
                 created_at TEXT NOT NULL,
                 prompt_tokens INTEGER DEFAULT 0,
                 completion_tokens INTEGER DEFAULT 0
             );

             CREATE TABLE IF NOT EXISTS task_krs (
                 task_id TEXT NOT NULL,
                 kr_id TEXT NOT NULL,
                 PRIMARY KEY (task_id, kr_id)
             );

             CREATE TABLE IF NOT EXISTS task_reqs (
                 task_id TEXT NOT NULL,
                 req_id TEXT NOT NULL,
                 PRIMARY KEY (task_id, req_id)
             );

             CREATE TABLE IF NOT EXISTS traceability_reports (
                 task_id TEXT PRIMARY KEY,
                 engine TEXT NOT NULL,
                 total_reqs INTEGER NOT NULL,
                 covered_reqs INTEGER NOT NULL,
                 coverage_pct REAL NOT NULL,
                 is_compliant INTEGER NOT NULL,
                 timestamp TEXT NOT NULL,
                 tests_passed INTEGER DEFAULT 0,
                 tests_failed INTEGER DEFAULT 0,
                 tests_unexecuted INTEGER DEFAULT 0,
                 line_coverage_pct REAL,
                 report_artifact TEXT
             );

             CREATE TABLE IF NOT EXISTS vcs_outcomes (
                 pr_id TEXT PRIMARY KEY,
                 task_id TEXT,
                 repo TEXT NOT NULL,
                 pr_number INTEGER NOT NULL,
                 state TEXT NOT NULL,
                 opened_at TEXT NOT NULL,
                 first_review_at TEXT,
                 merged_at TEXT,
                 human_review_rounds INTEGER NOT NULL DEFAULT 0,
                 human_commits_added INTEGER NOT NULL DEFAULT 0,
                 ci_runs_count INTEGER NOT NULL DEFAULT 0,
                 ci_failed_first_run INTEGER NOT NULL DEFAULT 0,
                 reverted INTEGER NOT NULL DEFAULT 0,
                 lead_time_sec REAL,
                 synced_at TEXT NOT NULL
             );
             CREATE INDEX IF NOT EXISTS idx_vcs_outcomes_task_id ON vcs_outcomes(task_id);
             CREATE INDEX IF NOT EXISTS idx_vcs_outcomes_state ON vcs_outcomes(state);
             CREATE INDEX IF NOT EXISTS idx_vcs_outcomes_merged_at ON vcs_outcomes(merged_at);

             CREATE TABLE IF NOT EXISTS prod_signals (
                 signal_id TEXT PRIMARY KEY,
                 task_id TEXT,
                 deploy_sha TEXT NOT NULL,
                 environment TEXT NOT NULL,
                 observed_at TEXT NOT NULL,
                 error_rate_delta REAL NOT NULL DEFAULT 0.0,
                 p95_latency_delta_ms REAL NOT NULL DEFAULT 0.0,
                 slo_budget_burn_pct REAL NOT NULL DEFAULT 0.0,
                 incident_triggered INTEGER NOT NULL DEFAULT 0,
                 mttr_sec REAL,
                 failure_class TEXT
             );
             CREATE INDEX IF NOT EXISTS idx_prod_signals_task_id ON prod_signals(task_id);
             CREATE INDEX IF NOT EXISTS idx_prod_signals_observed ON prod_signals(observed_at);

             CREATE TABLE IF NOT EXISTS kr_snapshots (
                 snapshot_id TEXT PRIMARY KEY,
                 kr_id TEXT NOT NULL,
                 observed_at TEXT NOT NULL,
                 value REAL NOT NULL,
                 progress_pct REAL NOT NULL,
                 latest_deploy_sha TEXT
             );
             CREATE INDEX IF NOT EXISTS idx_kr_snapshots_kr_id ON kr_snapshots(kr_id);
             CREATE INDEX IF NOT EXISTS idx_kr_snapshots_observed ON kr_snapshots(observed_at);

             CREATE TABLE IF NOT EXISTS sync_cursors (
                 source_key TEXT PRIMARY KEY,
                 cursor_val TEXT NOT NULL,
                 updated_at TEXT NOT NULL
             );

             CREATE TABLE IF NOT EXISTS factory_boms (
                 bom_id TEXT PRIMARY KEY,
                 task_id TEXT,
                 trace_id TEXT,
                 commit_sha TEXT,
                 created_at TEXT NOT NULL,
                 bom_digest TEXT NOT NULL,
                 signing_key_id TEXT NOT NULL,
                 signature_b64 TEXT NOT NULL,
                 target_name TEXT NOT NULL,
                 target_version TEXT NOT NULL,
                 cyclonedx_path TEXT NOT NULL,
                 slsa_path TEXT NOT NULL,
                 canonical_path TEXT NOT NULL,
                 substrate_type TEXT NOT NULL,
                 substrate_fingerprint TEXT NOT NULL
             );

             CREATE TABLE IF NOT EXISTS bom_artifacts (
                 artifact_id TEXT PRIMARY KEY,
                 bom_id TEXT NOT NULL,
                 name TEXT NOT NULL,
                 path TEXT NOT NULL,
                 sha256 TEXT NOT NULL,
                 sha512 TEXT NOT NULL,
                 size_bytes INTEGER NOT NULL,
                 mime_type TEXT,
                 FOREIGN KEY(bom_id) REFERENCES factory_boms(bom_id) ON DELETE CASCADE
             );

             CREATE TABLE IF NOT EXISTS bom_materials (
                 material_id TEXT PRIMARY KEY,
                 bom_id TEXT NOT NULL,
                 plane TEXT NOT NULL,
                 category TEXT NOT NULL,
                 name TEXT NOT NULL,
                 version TEXT,
                 hash TEXT NOT NULL,
                 details_json TEXT,
                 FOREIGN KEY(bom_id) REFERENCES factory_boms(bom_id) ON DELETE CASCADE
             );

             CREATE INDEX IF NOT EXISTS idx_factory_boms_commit ON factory_boms(commit_sha);
             CREATE INDEX IF NOT EXISTS idx_factory_boms_task ON factory_boms(task_id);
             CREATE INDEX IF NOT EXISTS idx_bom_artifacts_sha ON bom_artifacts(sha256);
             CREATE INDEX IF NOT EXISTS idx_bom_materials_plane ON bom_materials(plane, name);

             CREATE TABLE IF NOT EXISTS task_queue (
                 task_id TEXT PRIMARY KEY,
                 role TEXT NOT NULL,
                 req_ids TEXT NOT NULL,
                 kr_ids TEXT NOT NULL,
                 priority INTEGER NOT NULL DEFAULT 100,
                 status TEXT NOT NULL,
                 attempt_count INTEGER NOT NULL DEFAULT 0,
                 model_tier TEXT NOT NULL DEFAULT 'local',
                 assigned_uid INTEGER,
                 proxy_port INTEGER,
                 lease_expires_at INTEGER,
                 failure_context TEXT,
                 created_at TEXT NOT NULL,
                 updated_at TEXT NOT NULL
             );
             CREATE INDEX IF NOT EXISTS idx_task_queue_status_prio ON task_queue(status, priority, created_at);

             CREATE TABLE IF NOT EXISTS worker_leases (
                 slot_id INTEGER PRIMARY KEY,
                 uid INTEGER NOT NULL UNIQUE,
                 proxy_port INTEGER NOT NULL UNIQUE,
                 task_id TEXT,
                 leased_at INTEGER,
                 expires_at INTEGER
             );

             CREATE TABLE IF NOT EXISTS eval_results (
                 eval_id TEXT PRIMARY KEY,
                 task_id TEXT NOT NULL,
                 trace_id TEXT NOT NULL,
                 rubric_id TEXT NOT NULL,
                 stage TEXT NOT NULL,
                 judge_model TEXT NOT NULL,
                 score REAL NOT NULL,
                 confidence REAL NOT NULL,
                 passed INTEGER NOT NULL,
                 escalated INTEGER NOT NULL,
                 rationale TEXT,
                 checklist_json TEXT NOT NULL,
                 cost_usd REAL DEFAULT 0.0,
                 evaluated_at TEXT NOT NULL
             );
             CREATE INDEX IF NOT EXISTS idx_eval_results_task ON eval_results(task_id);
             CREATE INDEX IF NOT EXISTS idx_eval_results_rubric ON eval_results(rubric_id);
             CREATE INDEX IF NOT EXISTS idx_eval_results_evaluated_at ON eval_results(evaluated_at);

             CREATE TABLE IF NOT EXISTS requirement_links (
                 id TEXT PRIMARY KEY,
                 task_id TEXT,
                 req_id TEXT NOT NULL,
                 engine TEXT NOT NULL,
                 impl_covered INTEGER NOT NULL,
                 test_covered INTEGER NOT NULL,
                 test_passed INTEGER NOT NULL,
                 line_coverage_pct REAL,
                 verified_at TEXT NOT NULL
             );
             CREATE INDEX IF NOT EXISTS idx_req_links_task ON requirement_links(task_id);
             CREATE INDEX IF NOT EXISTS idx_req_links_req ON requirement_links(req_id);

             CREATE TABLE IF NOT EXISTS design_gate_results (
                 result_id TEXT PRIMARY KEY,
                 task_id TEXT,
                 platform TEXT NOT NULL,
                 token_violations INTEGER NOT NULL DEFAULT 0,
                 raw_primitive_violations INTEGER NOT NULL DEFAULT 0,
                 new_components_count INTEGER NOT NULL DEFAULT 0,
                 needs_design_review INTEGER NOT NULL DEFAULT 0,
                 a11y_violations INTEGER NOT NULL DEFAULT 0,
                 visual_diff_pct REAL NOT NULL DEFAULT 0.0,
                 status TEXT NOT NULL,
                 created_at TEXT NOT NULL
             );
             CREATE INDEX IF NOT EXISTS idx_design_gate_results_task ON design_gate_results(task_id);
             CREATE INDEX IF NOT EXISTS idx_design_gate_results_platform ON design_gate_results(platform);

             CREATE TABLE IF NOT EXISTS optimization_events (
                 event_id TEXT PRIMARY KEY,
                 signal_tier TEXT NOT NULL,
                 trigger_kind TEXT NOT NULL,
                 fingerprint TEXT NOT NULL,
                 details_json TEXT NOT NULL,
                 action_taken TEXT NOT NULL,
                 linked_task_id TEXT,
                 created_at TEXT NOT NULL
             );
             CREATE INDEX IF NOT EXISTS idx_opt_events_fingerprint ON optimization_events(fingerprint);
             CREATE INDEX IF NOT EXISTS idx_opt_events_created ON optimization_events(created_at);

             CREATE TABLE IF NOT EXISTS sca_gate_results (
                 result_id TEXT PRIMARY KEY,
                 task_id TEXT,
                 scanner TEXT NOT NULL,
                 is_compliant INTEGER NOT NULL,
                 vulnerabilities_found INTEGER NOT NULL,
                 blocking_count INTEGER NOT NULL,
                 summary TEXT,
                 created_at TEXT NOT NULL
             );
             CREATE INDEX IF NOT EXISTS idx_sca_gate_results_task ON sca_gate_results(task_id);",
        )
        .context("Failed to initialize canonical database tables")?;

        Ok(Self {
            conn: Mutex::new(conn),
            path: db_path.to_path_buf(),
        })
    }

    pub fn path(&self) -> &Path {
        &self.path
    }
}

pub fn parse_timestamp_epoch_sec(s: &str) -> Option<i64> {
    let trimmed = s.trim();
    if let Ok(v) = trimmed.parse::<i64>() {
        return Some(v);
    }
    if trimmed.len() >= 10 {
        let year: i32 = trimmed[0..4].parse().ok()?;
        let month: u32 = trimmed[5..7].parse().ok()?;
        let day: u32 = trimmed[8..10].parse().ok()?;
        let (hour, min, sec) = if trimmed.len() >= 19
            && (trimmed.as_bytes()[10] == b'T' || trimmed.as_bytes()[10] == b' ')
        {
            let h: u32 = trimmed[11..13].parse().ok()?;
            let m: u32 = trimmed[14..16].parse().ok()?;
            let s: u32 = trimmed[17..19].parse().ok()?;
            (h, m, s)
        } else {
            (0, 0, 0)
        };
        let days_before_month = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334];
        let is_leap = (year % 4 == 0 && year % 100 != 0) || (year % 400 == 0);
        let mut days = (year - 1970) as i64 * 365 + ((year - 1969) / 4) as i64
            - ((year - 1901) / 100) as i64
            + ((year - 1601) / 400) as i64;
        if (1..=12).contains(&month) {
            days += days_before_month[(month - 1) as usize] as i64;
            if month > 2 && is_leap {
                days += 1;
            }
        }
        days += (day as i64) - 1;
        let total_sec = days * 86400 + hour as i64 * 3600 + min as i64 * 60 + sec as i64;
        return Some(total_sec);
    }
    None
}

impl FactoryAnalyticsStore for SqliteAnalyticsStore {
    fn record_task(&self, task_ctx: &TaskContext, status: &str) -> Result<()> {
        let conn = self.conn.lock().unwrap();
        let now_iso = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_secs().to_string())
            .unwrap_or_default();

        conn.execute(
            "INSERT INTO tasks (task_id, trace_id, objective_id, agent_role, model, cost_usd, status, created_at)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)
             ON CONFLICT(task_id) DO UPDATE SET
                 status = excluded.status,
                 cost_usd = coalesce(excluded.cost_usd, tasks.cost_usd);",
            params![
                task_ctx.task_id,
                task_ctx.trace_id,
                task_ctx.objective_id,
                task_ctx.agent_role,
                task_ctx.model_profile,
                task_ctx.cost_usd,
                status,
                now_iso
            ],
        )?;

        for kr in &task_ctx.kr_ids {
            conn.execute(
                "INSERT OR IGNORE INTO task_krs (task_id, kr_id) VALUES (?1, ?2)",
                params![task_ctx.task_id, kr],
            )?;
        }

        for req in &task_ctx.req_ids {
            conn.execute(
                "INSERT OR IGNORE INTO task_reqs (task_id, req_id) VALUES (?1, ?2)",
                params![task_ctx.task_id, req],
            )?;
        }

        Ok(())
    }

    fn record_traceability(&self, task_id: &str, report: &TraceabilityReport) -> Result<()> {
        let conn = self.conn.lock().unwrap();
        let now_iso = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_secs().to_string())
            .unwrap_or_default();

        conn.execute(
            "INSERT INTO traceability_reports (
                 task_id, engine, total_reqs, covered_reqs, coverage_pct, is_compliant, timestamp,
                 tests_passed, tests_failed, tests_unexecuted, line_coverage_pct, report_artifact
             )
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12)
             ON CONFLICT(task_id) DO UPDATE SET
                 engine = excluded.engine,
                 total_reqs = excluded.total_reqs,
                 covered_reqs = excluded.covered_reqs,
                 coverage_pct = excluded.coverage_pct,
                 is_compliant = excluded.is_compliant,
                 timestamp = excluded.timestamp,
                 tests_passed = excluded.tests_passed,
                 tests_failed = excluded.tests_failed,
                 tests_unexecuted = excluded.tests_unexecuted,
                 line_coverage_pct = excluded.line_coverage_pct,
                 report_artifact = excluded.report_artifact;",
            params![
                task_id,
                report.engine,
                report.total_requirements as i64,
                report.covered_requirements as i64,
                report.coverage_pct,
                if report.is_compliant { 1 } else { 0 },
                now_iso,
                report.tests_passed as i64,
                report.tests_failed as i64,
                report.tests_unexecuted as i64,
                report.line_coverage_pct,
                report.report_artifact,
            ],
        )?;
        drop(conn);

        self.insert_requirement_links(Some(task_id), &report.engine, report)?;

        Ok(())
    }

    fn record_design_gate_report(
        &self,
        task_id: Option<&str>,
        report: &crate::design::DesignGateReport,
    ) -> Result<()> {
        let conn = self.conn.lock().unwrap();
        let now_iso = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_secs().to_string())
            .unwrap_or_default();

        let token_violations = report
            .violations
            .iter()
            .filter(|v| v.rule == "no_hardcoded_color" || v.rule == "unresolved_contract_token")
            .count();
        let raw_primitive_violations = report
            .violations
            .iter()
            .filter(|v| v.rule == "raw_primitive_violation")
            .count();
        let new_components_count = report.new_components.len();
        let needs_design_review = report.needs_design_review;

        if report.platform_results.is_empty() {
            let result_id = format!("{}:workspace", task_id.unwrap_or("global"));
            conn.execute(
                "INSERT INTO design_gate_results (
                     result_id, task_id, platform, token_violations, raw_primitive_violations,
                     new_components_count, needs_design_review, a11y_violations, visual_diff_pct,
                     status, created_at
                 )
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11)
                 ON CONFLICT(result_id) DO UPDATE SET
                     token_violations = excluded.token_violations,
                     raw_primitive_violations = excluded.raw_primitive_violations,
                     new_components_count = excluded.new_components_count,
                     needs_design_review = excluded.needs_design_review,
                     a11y_violations = excluded.a11y_violations,
                     visual_diff_pct = excluded.visual_diff_pct,
                     status = excluded.status,
                     created_at = excluded.created_at;",
                params![
                    result_id,
                    task_id,
                    "workspace",
                    token_violations as i64,
                    raw_primitive_violations as i64,
                    new_components_count as i64,
                    if needs_design_review { 1 } else { 0 },
                    report.a11y_violations.len() as i64,
                    0.0f64,
                    if report.is_compliant {
                        "passed"
                    } else {
                        "failed"
                    },
                    now_iso,
                ],
            )?;
        } else {
            for (platform, pres) in &report.platform_results {
                let result_id = format!("{}:{}", task_id.unwrap_or("global"), platform);
                let plat_a11y = report
                    .a11y_violations
                    .iter()
                    .filter(|a| {
                        a.id.contains(platform)
                            || a.target.as_deref().unwrap_or("").contains(platform)
                    })
                    .count();
                let plat_diff_pct = report
                    .visual_diff_failures
                    .iter()
                    .map(|f| f.diff_pct)
                    .fold(0.0f64, f64::max);

                conn.execute(
                    "INSERT INTO design_gate_results (
                         result_id, task_id, platform, token_violations, raw_primitive_violations,
                         new_components_count, needs_design_review, a11y_violations, visual_diff_pct,
                         status, created_at
                     )
                     VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11)
                     ON CONFLICT(result_id) DO UPDATE SET
                         token_violations = excluded.token_violations,
                         raw_primitive_violations = excluded.raw_primitive_violations,
                         new_components_count = excluded.new_components_count,
                         needs_design_review = excluded.needs_design_review,
                         a11y_violations = excluded.a11y_violations,
                         visual_diff_pct = excluded.visual_diff_pct,
                         status = excluded.status,
                         created_at = excluded.created_at;",
                    params![
                        result_id,
                        task_id,
                        platform,
                        token_violations as i64,
                        raw_primitive_violations as i64,
                        new_components_count as i64,
                        if needs_design_review { 1 } else { 0 },
                        plat_a11y as i64,
                        plat_diff_pct,
                        pres.status,
                        now_iso,
                    ],
                )?;
            }
        }

        Ok(())
    }

    fn get_task_design_gate_results(&self, task_id: &str) -> Result<Vec<DesignGateResultRecord>> {
        let conn = self.conn.lock().unwrap();
        let mut stmt = conn.prepare(
            "SELECT result_id, task_id, platform, token_violations, raw_primitive_violations,
                    new_components_count, needs_design_review, a11y_violations, visual_diff_pct,
                    status, created_at
             FROM design_gate_results WHERE task_id = ?1 ORDER BY platform ASC",
        )?;

        let rows = stmt.query_map(params![task_id], |row| {
            Ok(DesignGateResultRecord {
                result_id: row.get(0)?,
                task_id: row.get(1)?,
                platform: row.get(2)?,
                token_violations: row.get::<_, i64>(3)? as usize,
                raw_primitive_violations: row.get::<_, i64>(4)? as usize,
                new_components_count: row.get::<_, i64>(5)? as usize,
                needs_design_review: row.get::<_, i64>(6)? != 0,
                a11y_violations: row.get::<_, i64>(7)? as usize,
                visual_diff_pct: row.get(8)?,
                status: row.get(9)?,
                created_at: row.get(10)?,
            })
        })?;

        let mut results = Vec::new();
        for r in rows {
            results.push(r?);
        }
        Ok(results)
    }

    fn record_sca_gate_report(
        &self,
        task_id: Option<&str>,
        report: &crate::sca::ScaGateReport,
    ) -> Result<()> {
        let conn = self.conn.lock().unwrap();
        let now_iso = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_secs().to_string())
            .unwrap_or_default();
        let result_id = format!("{}:sca", task_id.unwrap_or("global"));

        conn.execute(
            "INSERT INTO sca_gate_results (
                result_id, task_id, scanner, is_compliant, vulnerabilities_found,
                blocking_count, summary, created_at
            ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)
            ON CONFLICT(result_id) DO UPDATE SET
                scanner = excluded.scanner,
                is_compliant = excluded.is_compliant,
                vulnerabilities_found = excluded.vulnerabilities_found,
                blocking_count = excluded.blocking_count,
                summary = excluded.summary,
                created_at = excluded.created_at;",
            params![
                result_id,
                task_id,
                report.scanner,
                if report.is_compliant { 1 } else { 0 },
                report.vulnerabilities_found as i64,
                report.blocking_vulnerabilities.len() as i64,
                report.summary,
                now_iso,
            ],
        )?;
        Ok(())
    }

    fn get_sca_gate_report(&self, task_id: &str) -> Result<Option<ScaGateRecord>> {
        let conn = self.conn.lock().unwrap();
        let mut stmt = conn.prepare(
            "SELECT result_id, task_id, scanner, is_compliant, vulnerabilities_found,
                    blocking_count, summary, created_at
             FROM sca_gate_results WHERE task_id = ?1",
        )?;
        let mut rows = stmt.query_map(params![task_id], |row| {
            Ok(ScaGateRecord {
                result_id: row.get(0)?,
                task_id: row.get(1)?,
                scanner: row.get(2)?,
                is_compliant: row.get::<_, i64>(3)? != 0,
                vulnerabilities_found: row.get::<_, i64>(4)? as usize,
                blocking_count: row.get::<_, i64>(5)? as usize,
                summary: row.get(6)?,
                created_at: row.get(7)?,
            })
        })?;

        if let Some(r) = rows.next() {
            Ok(Some(r?))
        } else {
            Ok(None)
        }
    }

    fn insert_requirement_links(
        &self,
        task_id: Option<&str>,
        engine: &str,
        report: &TraceabilityReport,
    ) -> Result<()> {
        let conn = self.conn.lock().unwrap();
        let now_iso = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_secs().to_string())
            .unwrap_or_default();

        for (req_id, detail) in &report.details {
            let link_id = format!("{}:{}:{}", task_id.unwrap_or("global"), engine, req_id);
            conn.execute(
                "INSERT INTO requirement_links (
                     id, task_id, req_id, engine, impl_covered, test_covered, test_passed, line_coverage_pct, verified_at
                 )
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9)
                 ON CONFLICT(id) DO UPDATE SET
                     impl_covered = excluded.impl_covered,
                     test_covered = excluded.test_covered,
                     test_passed = excluded.test_passed,
                     line_coverage_pct = excluded.line_coverage_pct,
                     verified_at = excluded.verified_at;",
                params![
                    link_id,
                    task_id,
                    req_id,
                    engine,
                    if detail.has_impl { 1 } else { 0 },
                    if detail.has_test { 1 } else { 0 },
                    if detail.test_passed { 1 } else { 0 },
                    detail.line_coverage_pct,
                    now_iso,
                ],
            )?;
        }

        Ok(())
    }

    fn get_requirement_links(&self, req_id: &str) -> Result<Vec<RequirementLinkRecord>> {
        let conn = self.conn.lock().unwrap();
        let mut stmt = conn.prepare(
            "SELECT id, task_id, req_id, engine, impl_covered, test_covered, test_passed, line_coverage_pct, verified_at
             FROM requirement_links WHERE req_id = ?1 ORDER BY verified_at DESC",
        )?;

        let rows = stmt.query_map(params![req_id], |row| {
            Ok(RequirementLinkRecord {
                id: row.get(0)?,
                task_id: row.get(1)?,
                req_id: row.get(2)?,
                engine: row.get(3)?,
                impl_covered: row.get::<_, i64>(4)? != 0,
                test_covered: row.get::<_, i64>(5)? != 0,
                test_passed: row.get::<_, i64>(6)? != 0,
                line_coverage_pct: row.get(7)?,
                verified_at: row.get(8)?,
            })
        })?;

        let mut results = Vec::new();
        for r in rows {
            results.push(r?);
        }
        Ok(results)
    }

    fn get_task_requirement_links(&self, task_id: &str) -> Result<Vec<RequirementLinkRecord>> {
        let conn = self.conn.lock().unwrap();
        let mut stmt = conn.prepare(
            "SELECT id, task_id, req_id, engine, impl_covered, test_covered, test_passed, line_coverage_pct, verified_at
             FROM requirement_links WHERE task_id = ?1 ORDER BY req_id ASC",
        )?;

        let rows = stmt.query_map(params![task_id], |row| {
            Ok(RequirementLinkRecord {
                id: row.get(0)?,
                task_id: row.get(1)?,
                req_id: row.get(2)?,
                engine: row.get(3)?,
                impl_covered: row.get::<_, i64>(4)? != 0,
                test_covered: row.get::<_, i64>(5)? != 0,
                test_passed: row.get::<_, i64>(6)? != 0,
                line_coverage_pct: row.get(7)?,
                verified_at: row.get(8)?,
            })
        })?;

        let mut results = Vec::new();
        for r in rows {
            results.push(r?);
        }
        Ok(results)
    }

    fn record_vcs_outcome(&self, task_id: &str, commit_sha: &str, valid: bool) -> Result<()> {
        let now_sec = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or(0);
        let record = VcsOutcomeRecord {
            pr_id: format!("local-{}", task_id),
            task_id: Some(task_id.to_string()),
            repo: "local".to_string(),
            pr_number: 0,
            state: if valid {
                "merged".to_string()
            } else {
                "closed".to_string()
            },
            opened_at: format!("{}", now_sec),
            first_review_at: None,
            merged_at: if valid {
                Some(format!("{}", now_sec))
            } else {
                None
            },
            human_review_rounds: 0,
            human_commits_added: 0,
            ci_runs_count: 1,
            ci_failed_first_run: !valid,
            reverted: false,
            lead_time_sec: Some(0.0),
            synced_at: format!("{}", now_sec),
        };
        self.upsert_vcs_outcome(&record)?;
        let _ = commit_sha;
        Ok(())
    }

    fn get_task(&self, task_id: &str) -> Result<Option<TaskRecord>> {
        let conn = self.conn.lock().unwrap();
        let mut stmt = conn.prepare(
            "SELECT task_id, trace_id, objective_id, agent_role, model, cost_usd, status, created_at,
                    coalesce(prompt_tokens, 0), coalesce(completion_tokens, 0)
             FROM tasks WHERE task_id = ?1",
        )?;

        let mut rows = stmt.query(params![task_id])?;
        if let Some(row) = rows.next()? {
            let tid: String = row.get(0)?;
            let trace_id: String = row.get(1)?;
            let objective_id: Option<String> = row.get(2)?;
            let agent_role: Option<String> = row.get(3)?;
            let model: Option<String> = row.get(4)?;
            let cost_usd: Option<f64> = row.get(5)?;
            let status: String = row.get(6)?;
            let created_at: String = row.get(7)?;
            let prompt_tokens: u64 = row.get::<_, i64>(8)? as u64;
            let completion_tokens: u64 = row.get::<_, i64>(9)? as u64;

            drop(rows);
            drop(stmt);

            // Fetch KRs
            let mut kr_stmt = conn.prepare("SELECT kr_id FROM task_krs WHERE task_id = ?1")?;
            let kr_rows = kr_stmt.query_map(params![task_id], |r| r.get(0))?;
            let kr_ids: Vec<String> = kr_rows.filter_map(|r| r.ok()).collect();

            // Fetch Reqs
            let mut req_stmt = conn.prepare("SELECT req_id FROM task_reqs WHERE task_id = ?1")?;
            let req_rows = req_stmt.query_map(params![task_id], |r| r.get(0))?;
            let req_ids: Vec<String> = req_rows.filter_map(|r| r.ok()).collect();

            return Ok(Some(TaskRecord {
                task_id: tid,
                trace_id,
                objective_id,
                agent_role,
                model,
                cost_usd,
                status,
                created_at,
                prompt_tokens,
                completion_tokens,
                kr_ids,
                req_ids,
            }));
        }

        Ok(None)
    }

    fn list_tasks(&self, limit: usize) -> Result<Vec<TaskRecord>> {
        let conn = self.conn.lock().unwrap();
        let mut stmt = conn.prepare(
            "SELECT task_id, trace_id, objective_id, agent_role, model, cost_usd, status, created_at,
                    coalesce(prompt_tokens, 0), coalesce(completion_tokens, 0)
             FROM tasks ORDER BY created_at DESC LIMIT ?1",
        )?;

        let rows = stmt.query_map(params![limit as i64], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, Option<String>>(2)?,
                row.get::<_, Option<String>>(3)?,
                row.get::<_, Option<String>>(4)?,
                row.get::<_, Option<f64>>(5)?,
                row.get::<_, String>(6)?,
                row.get::<_, String>(7)?,
                row.get::<_, i64>(8)? as u64,
                row.get::<_, i64>(9)? as u64,
            ))
        })?;

        let mut tasks = Vec::new();
        for r in rows.flatten() {
            tasks.push(TaskRecord {
                task_id: r.0,
                trace_id: r.1,
                objective_id: r.2,
                agent_role: r.3,
                model: r.4,
                cost_usd: r.5,
                status: r.6,
                created_at: r.7,
                prompt_tokens: r.8,
                completion_tokens: r.9,
                kr_ids: Vec::new(),
                req_ids: Vec::new(),
            });
        }

        Ok(tasks)
    }

    fn get_kr_spend(&self, kr_id: &str) -> Result<f64> {
        let conn = self.conn.lock().unwrap();
        let spend: f64 = conn.query_row(
            "SELECT COALESCE(SUM(t.cost_usd), 0.0)
             FROM tasks t
             JOIN task_krs tk ON t.task_id = tk.task_id
             WHERE tk.kr_id = ?1",
            params![kr_id],
            |row| row.get(0),
        )?;
        Ok(spend)
    }

    fn get_recent_success_rate(&self, limit: usize) -> Result<(usize, usize, f64)> {
        let conn = self.conn.lock().unwrap();
        let mut stmt =
            conn.prepare("SELECT status FROM tasks ORDER BY created_at DESC LIMIT ?1")?;
        let rows = stmt.query_map(params![limit as i64], |row| row.get::<_, String>(0))?;
        let mut total = 0;
        let mut successful = 0;
        for status in rows.flatten() {
            total += 1;
            if status == "verified" || status == "completed" {
                successful += 1;
            }
        }
        let rate = if total == 0 {
            100.0
        } else {
            (successful as f64 / total as f64) * 100.0
        };
        Ok((total, successful, rate))
    }

    fn get_analytics_summary(&self) -> Result<AnalyticsSummary> {
        let conn = self.conn.lock().unwrap();
        let total_tasks = conn.query_row("SELECT COUNT(*) FROM tasks", [], |r| {
            r.get::<_, i64>(0).map(|c| c as usize)
        })?;
        let verified_tasks = conn.query_row(
            "SELECT COUNT(*) FROM tasks WHERE status = 'verified' OR status = 'completed'",
            [],
            |r| r.get::<_, i64>(0).map(|c| c as usize),
        )?;
        let failed_tasks = conn.query_row(
            "SELECT COUNT(*) FROM tasks WHERE status = 'failed'",
            [],
            |r| r.get::<_, i64>(0).map(|c| c as usize),
        )?;
        let total_cost_usd: f64 =
            conn.query_row("SELECT COALESCE(SUM(cost_usd), 0.0) FROM tasks", [], |r| {
                r.get(0)
            })?;
        let avg_traceability_pct: f64 = conn.query_row(
            "SELECT COALESCE(AVG(coverage_pct), 100.0) FROM traceability_reports",
            [],
            |r| r.get(0),
        )?;

        let mut kr_stmt = conn.prepare(
            "SELECT tk.kr_id, COALESCE(SUM(t.cost_usd), 0.0)
             FROM task_krs tk
             JOIN tasks t ON tk.task_id = t.task_id
             GROUP BY tk.kr_id",
        )?;
        let kr_rows =
            kr_stmt.query_map([], |r| Ok((r.get::<_, String>(0)?, r.get::<_, f64>(1)?)))?;
        let mut kr_spends = HashMap::new();
        for item in kr_rows.flatten() {
            kr_spends.insert(item.0, item.1);
        }

        Ok(AnalyticsSummary {
            total_tasks,
            verified_tasks,
            failed_tasks,
            total_cost_usd,
            avg_traceability_pct,
            kr_spends,
        })
    }

    fn upsert_vcs_outcome(&self, record: &VcsOutcomeRecord) -> Result<()> {
        let conn = self.conn.lock().unwrap();
        conn.execute(
            "INSERT INTO vcs_outcomes (
                 pr_id, task_id, repo, pr_number, state, opened_at, first_review_at, merged_at,
                 human_review_rounds, human_commits_added, ci_runs_count, ci_failed_first_run,
                 reverted, lead_time_sec, synced_at
             ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14, ?15)
             ON CONFLICT(pr_id) DO UPDATE SET
                 task_id = coalesce(excluded.task_id, vcs_outcomes.task_id),
                 repo = excluded.repo,
                 pr_number = excluded.pr_number,
                 state = excluded.state,
                 opened_at = excluded.opened_at,
                 first_review_at = coalesce(excluded.first_review_at, vcs_outcomes.first_review_at),
                 merged_at = coalesce(excluded.merged_at, vcs_outcomes.merged_at),
                 human_review_rounds = excluded.human_review_rounds,
                 human_commits_added = excluded.human_commits_added,
                 ci_runs_count = excluded.ci_runs_count,
                 ci_failed_first_run = excluded.ci_failed_first_run,
                 reverted = excluded.reverted,
                 lead_time_sec = coalesce(excluded.lead_time_sec, vcs_outcomes.lead_time_sec),
                 synced_at = excluded.synced_at;",
            params![
                record.pr_id,
                record.task_id,
                record.repo,
                record.pr_number as i64,
                record.state,
                record.opened_at,
                record.first_review_at,
                record.merged_at,
                record.human_review_rounds as i64,
                record.human_commits_added as i64,
                record.ci_runs_count as i64,
                if record.ci_failed_first_run { 1 } else { 0 },
                if record.reverted { 1 } else { 0 },
                record.lead_time_sec,
                record.synced_at,
            ],
        )?;
        Ok(())
    }

    fn insert_prod_signal(&self, record: &ProdSignalRecord) -> Result<()> {
        let conn = self.conn.lock().unwrap();
        conn.execute(
            "INSERT INTO prod_signals (
                 signal_id, task_id, deploy_sha, environment, observed_at,
                 error_rate_delta, p95_latency_delta_ms, slo_budget_burn_pct,
                 incident_triggered, mttr_sec, failure_class
             ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11)
             ON CONFLICT(signal_id) DO NOTHING;",
            params![
                record.signal_id,
                record.task_id,
                record.deploy_sha,
                record.environment,
                record.observed_at,
                record.error_rate_delta,
                record.p95_latency_delta_ms,
                record.slo_budget_burn_pct,
                if record.incident_triggered { 1 } else { 0 },
                record.mttr_sec,
                record.failure_class,
            ],
        )?;
        Ok(())
    }

    fn insert_kr_snapshot(&self, record: &KrSnapshotRecord) -> Result<()> {
        let conn = self.conn.lock().unwrap();
        conn.execute(
            "INSERT INTO kr_snapshots (
                 snapshot_id, kr_id, observed_at, value, progress_pct, latest_deploy_sha
             ) VALUES (?1, ?2, ?3, ?4, ?5, ?6)
             ON CONFLICT(snapshot_id) DO UPDATE SET
                 value = excluded.value,
                 progress_pct = excluded.progress_pct,
                 latest_deploy_sha = coalesce(excluded.latest_deploy_sha, kr_snapshots.latest_deploy_sha);",
            params![
                record.snapshot_id,
                record.kr_id,
                record.observed_at,
                record.value,
                record.progress_pct,
                record.latest_deploy_sha,
            ],
        )?;
        Ok(())
    }

    fn get_sync_cursor(&self, source_key: &str) -> Result<Option<String>> {
        let conn = self.conn.lock().unwrap();
        let mut stmt = conn.prepare("SELECT cursor_val FROM sync_cursors WHERE source_key = ?1")?;
        let mut rows = stmt.query(params![source_key])?;
        if let Some(r) = rows.next()? {
            let val: String = r.get(0)?;
            Ok(Some(val))
        } else {
            Ok(None)
        }
    }

    fn set_sync_cursor(&self, source_key: &str, cursor_val: &str) -> Result<()> {
        let conn = self.conn.lock().unwrap();
        let now_sec = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_secs().to_string())
            .unwrap_or_default();
        conn.execute(
            "INSERT INTO sync_cursors (source_key, cursor_val, updated_at)
             VALUES (?1, ?2, ?3)
             ON CONFLICT(source_key) DO UPDATE SET
                 cursor_val = excluded.cursor_val,
                 updated_at = excluded.updated_at;",
            params![source_key, cursor_val, now_sec],
        )?;
        Ok(())
    }

    fn get_open_pr_count(&self) -> Result<usize> {
        let conn = self.conn.lock().unwrap();
        let count: i64 = conn
            .query_row(
                "SELECT COUNT(*) FROM vcs_outcomes WHERE state = 'open'",
                [],
                |r| r.get(0),
            )
            .unwrap_or(0);
        Ok(count as usize)
    }

    fn get_rolling_fpy(
        &self,
        window_days: u32,
        role: Option<&str>,
        model: Option<&str>,
    ) -> Result<f64> {
        let conn = self.conn.lock().unwrap();
        let now_sec = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or(0) as i64;
        let cutoff_sec = if window_days > 0 {
            Some(now_sec - (window_days as i64 * 86400))
        } else {
            None
        };

        let mut stmt = conn.prepare(
            "SELECT v.human_review_rounds, v.human_commits_added, v.ci_failed_first_run, v.reverted, v.merged_at, t.agent_role, t.model
             FROM vcs_outcomes v
             LEFT JOIN tasks t ON v.task_id = t.task_id
             WHERE v.state = 'merged'",
        )?;

        let rows = stmt.query_map([], |r| {
            let rounds: u32 = r.get(0)?;
            let commits: u32 = r.get(1)?;
            let ci_failed: bool = r.get::<_, i64>(2)? != 0;
            let reverted: bool = r.get::<_, i64>(3)? != 0;
            let merged_at: Option<String> = r.get(4)?;
            let r_role: Option<String> = r.get(5)?;
            let r_model: Option<String> = r.get(6)?;
            Ok((
                rounds, commits, ci_failed, reverted, merged_at, r_role, r_model,
            ))
        })?;

        let mut total = 0;
        let mut first_pass = 0;

        for r in rows {
            let (rounds, commits, ci_failed, reverted, merged_at, r_role, r_model) = r?;
            if let Some(cutoff) = cutoff_sec {
                if let Some(ref m_at) = merged_at {
                    if let Some(m_sec) = parse_timestamp_epoch_sec(m_at) {
                        if m_sec < cutoff {
                            continue;
                        }
                    }
                }
            }
            if let Some(req_role) = role {
                if r_role.as_deref() != Some(req_role) {
                    continue;
                }
            }
            if let Some(req_model) = model {
                if r_model.as_deref() != Some(req_model) {
                    continue;
                }
            }
            total += 1;
            if rounds == 0 && commits == 0 && !ci_failed && !reverted {
                first_pass += 1;
            }
        }

        if total == 0 {
            return Ok(1.0);
        }
        Ok(first_pass as f64 / total as f64)
    }

    fn get_rolling_cfr(&self, window_days: u32) -> Result<f64> {
        let report = self.get_dora_flow_report(window_days, None)?;
        Ok(report.change_failure_rate)
    }

    fn get_dora_flow_report(
        &self,
        window_days: u32,
        group_by: Option<&str>,
    ) -> Result<DoraFlowReport> {
        let conn = self.conn.lock().unwrap();

        let open_pr_queue_depth: i64 = conn
            .query_row(
                "SELECT COUNT(*) FROM vcs_outcomes WHERE state = 'open'",
                [],
                |r| r.get(0),
            )
            .unwrap_or(0);
        let open_pr_queue_depth = open_pr_queue_depth as usize;

        let now_sec = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or(0) as i64;

        let cutoff_sec = if window_days > 0 {
            Some(now_sec - (window_days as i64 * 86400))
        } else {
            None
        };

        let mut stmt = conn.prepare(
            "SELECT v.pr_id, v.task_id, v.repo, v.pr_number, v.state, v.opened_at,
                    v.first_review_at, v.merged_at, v.human_review_rounds, v.human_commits_added,
                    v.ci_runs_count, v.ci_failed_first_run, v.reverted, v.lead_time_sec, v.synced_at,
                    t.agent_role, t.model, t.objective_id, coalesce(t.cost_usd, 0.0), t.created_at
             FROM vcs_outcomes v
             LEFT JOIN tasks t ON v.task_id = t.task_id
             WHERE v.state = 'merged'",
        )?;

        struct MergedPrInfo {
            _pr_id: String,
            _task_id: Option<String>,
            repo: String,
            lead_time_sec: Option<f64>,
            first_pass: bool,
            failed: bool,
            cost_usd: f64,
            role: String,
            model: String,
            objective: String,
            flow_efficiency: Option<f64>,
        }

        let rows = stmt.query_map([], |r| {
            let pr_id: String = r.get(0)?;
            let task_id: Option<String> = r.get(1)?;
            let repo: String = r.get(2)?;
            let _pr_number: i64 = r.get(3)?;
            let _state: String = r.get(4)?;
            let opened_at: String = r.get(5)?;
            let _first_review_at: Option<String> = r.get(6)?;
            let merged_at: Option<String> = r.get(7)?;
            let human_review_rounds: u32 = r.get(8)?;
            let human_commits_added: u32 = r.get(9)?;
            let _ci_runs: u32 = r.get(10)?;
            let ci_failed_first: bool = r.get::<_, i64>(11)? != 0;
            let reverted: bool = r.get::<_, i64>(12)? != 0;
            let lead_time_sec: Option<f64> = r.get(13)?;
            let _synced_at: String = r.get(14)?;
            let role: Option<String> = r.get(15)?;
            let model: Option<String> = r.get(16)?;
            let objective: Option<String> = r.get(17)?;
            let cost_usd: f64 = r.get(18)?;
            let created_at: Option<String> = r.get(19)?;

            Ok((
                pr_id,
                task_id,
                repo,
                opened_at,
                merged_at,
                human_review_rounds,
                human_commits_added,
                ci_failed_first,
                reverted,
                lead_time_sec,
                role,
                model,
                objective,
                cost_usd,
                created_at,
            ))
        })?;

        let mut merged_prs: Vec<MergedPrInfo> = Vec::new();

        for r in rows {
            let (
                pr_id,
                task_id,
                repo,
                opened_at,
                merged_at,
                human_review_rounds,
                human_commits_added,
                ci_failed_first,
                reverted,
                lead_time_sec,
                role,
                model,
                objective,
                cost_usd,
                created_at,
            ) = r?;

            if let Some(cutoff) = cutoff_sec {
                if let Some(ref m_at) = merged_at {
                    if let Some(m_sec) = parse_timestamp_epoch_sec(m_at) {
                        if m_sec < cutoff {
                            continue;
                        }
                    }
                }
            }

            let mut failed = reverted;
            if !failed {
                if let Some(ref tid) = task_id {
                    let has_incident: bool = conn
                        .query_row(
                            "SELECT COUNT(*) FROM prod_signals WHERE task_id = ?1 AND incident_triggered = 1",
                            params![tid],
                            |row| row.get::<_, i64>(0),
                        )
                        .map(|c| c > 0)
                        .unwrap_or(false);
                    if has_incident {
                        failed = true;
                    }
                }
            }

            let first_pass = human_review_rounds == 0
                && human_commits_added == 0
                && !ci_failed_first
                && !reverted;

            let flow_eff = if let Some(lt) = lead_time_sec {
                if lt > 0.0 {
                    let active = if let (Some(c_str), o_str) = (created_at.as_deref(), &opened_at) {
                        if let (Some(c_sec), Some(o_sec)) = (
                            parse_timestamp_epoch_sec(c_str),
                            parse_timestamp_epoch_sec(o_str),
                        ) {
                            let diff = (o_sec - c_sec).max(1) as f64;
                            diff.min(lt)
                        } else {
                            lt
                        }
                    } else {
                        lt
                    };
                    Some((active / lt).clamp(0.0, 1.0))
                } else {
                    Some(1.0)
                }
            } else {
                None
            };

            merged_prs.push(MergedPrInfo {
                _pr_id: pr_id,
                _task_id: task_id,
                repo,
                lead_time_sec,
                first_pass,
                failed,
                cost_usd,
                role: role.unwrap_or_else(|| "unassigned".to_string()),
                model: model.unwrap_or_else(|| "default".to_string()),
                objective: objective.unwrap_or_else(|| "OBJ-OPS-MAINTENANCE".to_string()),
                flow_efficiency: flow_eff,
            });
        }

        let total_merged = merged_prs.len();

        let mut lead_times: Vec<f64> = merged_prs
            .iter()
            .filter_map(|p| p.lead_time_sec)
            .filter(|t| *t >= 0.0)
            .collect();
        lead_times.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));

        let (lead_time_median_sec, lead_time_p95_sec) = if lead_times.is_empty() {
            (None, None)
        } else {
            let mid = lead_times.len() / 2;
            let median = if lead_times.len().is_multiple_of(2) {
                (lead_times[mid - 1] + lead_times[mid]) / 2.0
            } else {
                lead_times[mid]
            };
            let p95_idx = ((lead_times.len() as f64 * 0.95).ceil() as usize)
                .saturating_sub(1)
                .min(lead_times.len() - 1);
            (Some(median), Some(lead_times[p95_idx]))
        };

        let deployment_frequency_per_day = if window_days > 0 {
            total_merged as f64 / window_days as f64
        } else {
            total_merged as f64
        };

        let first_pass_count = merged_prs.iter().filter(|p| p.first_pass).count();
        let first_pass_yield = if total_merged > 0 {
            first_pass_count as f64 / total_merged as f64
        } else {
            1.0
        };

        let failed_count = merged_prs.iter().filter(|p| p.failed).count();
        let change_failure_rate = if total_merged > 0 {
            failed_count as f64 / total_merged as f64
        } else {
            0.0
        };

        let mttr_avg_sec: Option<f64> = conn
            .query_row(
                "SELECT AVG(mttr_sec) FROM prod_signals WHERE incident_triggered = 1 AND mttr_sec IS NOT NULL",
                [],
                |r| r.get(0),
            )
            .ok();

        let flow_eff_vals: Vec<f64> = merged_prs
            .iter()
            .filter_map(|p| p.flow_efficiency)
            .collect();
        let flow_efficiency = if flow_eff_vals.is_empty() {
            1.0
        } else {
            flow_eff_vals.iter().sum::<f64>() / flow_eff_vals.len() as f64
        };

        let total_merged_cost: f64 = merged_prs.iter().map(|p| p.cost_usd).sum();
        let cost_per_merged_pr = if total_merged > 0 {
            Some(total_merged_cost / total_merged as f64)
        } else {
            None
        };

        let first_pass_cost: f64 = merged_prs
            .iter()
            .filter(|p| p.first_pass)
            .map(|p| p.cost_usd)
            .sum();
        let cost_per_first_pass_pr = if first_pass_count > 0 {
            Some(first_pass_cost / first_pass_count as f64)
        } else {
            None
        };

        let mut groups: HashMap<String, DoraFlowGroupMetrics> = HashMap::new();
        if let Some(dim) = group_by {
            let mut group_map: HashMap<String, Vec<&MergedPrInfo>> = HashMap::new();
            for p in &merged_prs {
                let key = match dim.to_lowercase().as_str() {
                    "okr" => p.objective.clone(),
                    "role" => p.role.clone(),
                    "model" => p.model.clone(),
                    "repo" => p.repo.clone(),
                    _ => p.repo.clone(),
                };
                group_map.entry(key).or_default().push(p);
            }

            for (k, items) in group_map {
                let n = items.len();
                let mut lts: Vec<f64> = items.iter().filter_map(|i| i.lead_time_sec).collect();
                lts.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
                let med = if lts.is_empty() {
                    None
                } else {
                    Some(lts[lts.len() / 2])
                };
                let fp = items.iter().filter(|i| i.first_pass).count();
                let fl = items.iter().filter(|i| i.failed).count();
                let c = items.iter().map(|i| i.cost_usd).sum();

                groups.insert(
                    k.clone(),
                    DoraFlowGroupMetrics {
                        group_key: k,
                        merged_prs: n,
                        lead_time_median_sec: med,
                        change_failure_rate: if n > 0 { fl as f64 / n as f64 } else { 0.0 },
                        first_pass_yield: if n > 0 { fp as f64 / n as f64 } else { 1.0 },
                        total_cost_usd: c,
                    },
                );
            }
        }

        Ok(DoraFlowReport {
            window_days,
            group_by: group_by.map(|s| s.to_string()),
            lead_time_median_sec,
            lead_time_p95_sec,
            deployment_frequency_per_day,
            change_failure_rate,
            mttr_avg_sec,
            first_pass_yield,
            flow_efficiency,
            open_pr_queue_depth,
            cost_per_merged_pr,
            cost_per_first_pass_pr,
            total_merged_prs: total_merged,
            groups,
        })
    }

    fn list_vcs_outcomes(&self, limit: usize) -> Result<Vec<VcsOutcomeRecord>> {
        let conn = self.conn.lock().unwrap();
        let mut stmt = conn.prepare(
            "SELECT pr_id, task_id, repo, pr_number, state, opened_at, first_review_at, merged_at,
                    human_review_rounds, human_commits_added, ci_runs_count, ci_failed_first_run,
                    reverted, lead_time_sec, synced_at
             FROM vcs_outcomes ORDER BY pr_number DESC LIMIT ?1",
        )?;
        let rows = stmt.query_map(params![limit as i64], |r| {
            Ok(VcsOutcomeRecord {
                pr_id: r.get(0)?,
                task_id: r.get(1)?,
                repo: r.get(2)?,
                pr_number: r.get::<_, i64>(3)? as u64,
                state: r.get(4)?,
                opened_at: r.get(5)?,
                first_review_at: r.get(6)?,
                merged_at: r.get(7)?,
                human_review_rounds: r.get(8)?,
                human_commits_added: r.get(9)?,
                ci_runs_count: r.get(10)?,
                ci_failed_first_run: r.get::<_, i64>(11)? != 0,
                reverted: r.get::<_, i64>(12)? != 0,
                lead_time_sec: r.get(13)?,
                synced_at: r.get(14)?,
            })
        })?;
        let mut list = Vec::new();
        for r in rows {
            list.push(r?);
        }
        Ok(list)
    }

    fn list_kr_snapshots(
        &self,
        kr_id: Option<&str>,
        limit: usize,
    ) -> Result<Vec<KrSnapshotRecord>> {
        let conn = self.conn.lock().unwrap();
        let mut list = Vec::new();
        if let Some(id) = kr_id {
            let mut stmt = conn.prepare(
                "SELECT snapshot_id, kr_id, observed_at, value, progress_pct, latest_deploy_sha
                 FROM kr_snapshots WHERE kr_id = ?1 ORDER BY observed_at DESC LIMIT ?2",
            )?;
            let rows = stmt.query_map(params![id, limit as i64], |r| {
                Ok(KrSnapshotRecord {
                    snapshot_id: r.get(0)?,
                    kr_id: r.get(1)?,
                    observed_at: r.get(2)?,
                    value: r.get(3)?,
                    progress_pct: r.get(4)?,
                    latest_deploy_sha: r.get(5)?,
                })
            })?;
            for r in rows {
                list.push(r?);
            }
        } else {
            let mut stmt = conn.prepare(
                "SELECT snapshot_id, kr_id, observed_at, value, progress_pct, latest_deploy_sha
                 FROM kr_snapshots ORDER BY observed_at DESC LIMIT ?1",
            )?;
            let rows = stmt.query_map(params![limit as i64], |r| {
                Ok(KrSnapshotRecord {
                    snapshot_id: r.get(0)?,
                    kr_id: r.get(1)?,
                    observed_at: r.get(2)?,
                    value: r.get(3)?,
                    progress_pct: r.get(4)?,
                    latest_deploy_sha: r.get(5)?,
                })
            })?;
            for r in rows {
                list.push(r?);
            }
        }
        Ok(list)
    }

    fn update_task_usage(
        &self,
        task_id: &str,
        prompt_tokens: u64,
        completion_tokens: u64,
        cost_usd: f64,
    ) -> Result<()> {
        let conn = self.conn.lock().unwrap();
        let updated = conn.execute(
            "UPDATE tasks SET
                 prompt_tokens = coalesce(prompt_tokens, 0) + ?1,
                 completion_tokens = coalesce(completion_tokens, 0) + ?2,
                 cost_usd = coalesce(cost_usd, 0.0) + ?3
             WHERE task_id = ?4",
            params![
                prompt_tokens as i64,
                completion_tokens as i64,
                cost_usd,
                task_id,
            ],
        )?;

        if updated == 0 {
            let now_sec = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .map(|d| d.as_secs().to_string())
                .unwrap_or_default();
            conn.execute(
                "INSERT INTO tasks (task_id, trace_id, status, created_at, prompt_tokens, completion_tokens, cost_usd)
                 VALUES (?1, ?1, 'in_progress', ?2, ?3, ?4, ?5)",
                params![
                    task_id,
                    now_sec,
                    prompt_tokens as i64,
                    completion_tokens as i64,
                    cost_usd,
                ],
            )?;
        }
        Ok(())
    }

    fn record_bom(
        &self,
        bom: &crate::bom::FactoryBom,
        cdx_path: &Path,
        slsa_path: &Path,
        canonical_path: &Path,
    ) -> Result<()> {
        let mut conn = self.conn.lock().unwrap();
        let tx = conn.transaction()?;

        let signing_key_id = bom
            .signature_info
            .as_ref()
            .map(|s| s.key_id.clone())
            .unwrap_or_default();
        let signature_b64 = bom
            .signature_info
            .as_ref()
            .map(|s| s.signature_b64.clone())
            .unwrap_or_default();
        let bom_digest = bom
            .signature_info
            .as_ref()
            .map(|s| s.bom_digest.clone())
            .unwrap_or_default();

        let substrate_type = bom.plane_substrate.backend.clone();
        let substrate_fingerprint = if let Some(ref tart) = bom.plane_substrate.tart_fingerprint {
            format!(
                "{}:{}:{}",
                tart.ipsw_build, tart.config_hash, tart.disk_digest
            )
        } else if let Some(ref incus) = bom.plane_substrate.incus_fingerprint {
            format!(
                "{}:{}:{}",
                incus.image_fingerprint, incus.config_hash, incus.rootfs_digest
            )
        } else {
            "host".to_string()
        };

        tx.execute(
            "INSERT OR REPLACE INTO factory_boms (
                 bom_id, task_id, trace_id, commit_sha, created_at, bom_digest,
                 signing_key_id, signature_b64, target_name, target_version,
                 cyclonedx_path, slsa_path, canonical_path, substrate_type, substrate_fingerprint
             ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14, ?15)",
            params![
                bom.bom_id,
                bom.task_id,
                bom.trace_id,
                bom.commit_sha,
                bom.created_at,
                bom_digest,
                signing_key_id,
                signature_b64,
                bom.target_name,
                bom.target_version,
                cdx_path.to_string_lossy().to_string(),
                slsa_path.to_string_lossy().to_string(),
                canonical_path.to_string_lossy().to_string(),
                substrate_type,
                substrate_fingerprint,
            ],
        )?;

        // Insert artifacts
        for (idx, art) in bom.artifacts.iter().enumerate() {
            let artifact_id = format!("{}-{}", bom.bom_id, idx);
            tx.execute(
                "INSERT OR REPLACE INTO bom_artifacts (
                     artifact_id, bom_id, name, path, sha256, sha512, size_bytes, mime_type
                 ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)",
                params![
                    artifact_id,
                    bom.bom_id,
                    art.name,
                    art.path,
                    art.sha256,
                    art.sha512,
                    art.size_bytes as i64,
                    art.mime_type,
                ],
            )?;
        }

        // Insert materials from 6 planes
        let mut mat_idx = 0;
        // 1. Dependencies
        for dep in &bom.plane_dependencies {
            let mat_id = format!("{}-mat-{}", bom.bom_id, mat_idx);
            mat_idx += 1;
            let details = serde_json::to_string(&serde_json::json!({
                "purl": dep.purl,
                "dep_type": format!("{:?}", dep.dep_type),
            }))
            .unwrap_or_default();
            tx.execute(
                "INSERT OR REPLACE INTO bom_materials (
                     material_id, bom_id, plane, category, name, version, hash, details_json
                 ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)",
                params![
                    mat_id,
                    bom.bom_id,
                    "dependency",
                    dep.ecosystem,
                    dep.name,
                    Some(dep.version.clone()),
                    dep.checksum.clone().unwrap_or_default(),
                    Some(details),
                ],
            )?;
        }

        // 2. Toolchain
        for tool in &bom.plane_toolchain {
            let mat_id = format!("{}-mat-{}", bom.bom_id, mat_idx);
            mat_idx += 1;
            let details = serde_json::to_string(&serde_json::json!({
                "path": tool.path,
                "commit_or_build": tool.commit_or_build,
            }))
            .unwrap_or_default();
            tx.execute(
                "INSERT OR REPLACE INTO bom_materials (
                     material_id, bom_id, plane, category, name, version, hash, details_json
                 ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)",
                params![
                    mat_id,
                    bom.bom_id,
                    "toolchain",
                    tool.kind,
                    tool.name,
                    Some(tool.version.clone()),
                    tool.binary_sha256.clone().unwrap_or_default(),
                    Some(details),
                ],
            )?;
        }

        // 3. Substrate
        {
            let mat_id = format!("{}-mat-{}", bom.bom_id, mat_idx);
            mat_idx += 1;
            tx.execute(
                "INSERT OR REPLACE INTO bom_materials (
                     material_id, bom_id, plane, category, name, version, hash, details_json
                 ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)",
                params![
                    mat_id,
                    bom.bom_id,
                    "substrate",
                    "hypervisor",
                    bom.plane_substrate.backend,
                    None::<String>,
                    substrate_fingerprint,
                    None::<String>,
                ],
            )?;
        }

        // 4. Agentic
        if let Some(ref m_root) = bom.plane_agentic.skills_merkle_root {
            let mat_id = format!("{}-mat-{}", bom.bom_id, mat_idx);
            mat_idx += 1;
            tx.execute(
                "INSERT OR REPLACE INTO bom_materials (
                     material_id, bom_id, plane, category, name, version, hash, details_json
                 ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)",
                params![
                    mat_id,
                    bom.bom_id,
                    "agentic",
                    "skills",
                    "skills_merkle_root",
                    None::<String>,
                    m_root,
                    None::<String>,
                ],
            )?;
        }

        // 5. Proxy
        if let Some(ref a_hash) = bom.plane_proxy.allowlist_ruleset_hash {
            let mat_id = format!("{}-mat-{}", bom.bom_id, mat_idx);
            mat_idx += 1;
            tx.execute(
                "INSERT OR REPLACE INTO bom_materials (
                     material_id, bom_id, plane, category, name, version, hash, details_json
                 ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)",
                params![
                    mat_id,
                    bom.bom_id,
                    "proxy",
                    "allowlist",
                    "allowlist_ruleset",
                    None::<String>,
                    a_hash,
                    None::<String>,
                ],
            )?;
        }

        // 6. Specs
        for (okr_id, hash) in &bom.plane_specs.okr_hashes {
            let mat_id = format!("{}-mat-{}", bom.bom_id, mat_idx);
            mat_idx += 1;
            tx.execute(
                "INSERT OR REPLACE INTO bom_materials (
                     material_id, bom_id, plane, category, name, version, hash, details_json
                 ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)",
                params![
                    mat_id,
                    bom.bom_id,
                    "spec",
                    "okr",
                    okr_id,
                    None::<String>,
                    hash,
                    None::<String>,
                ],
            )?;
        }

        tx.commit()?;
        Ok(())
    }

    fn get_bom(&self, bom_id: &str) -> Result<Option<BomRecord>> {
        let conn = self.conn.lock().unwrap();
        let mut stmt = conn.prepare(
            "SELECT bom_id, task_id, trace_id, commit_sha, created_at, bom_digest,
                    signing_key_id, signature_b64, target_name, target_version,
                    cyclonedx_path, slsa_path, canonical_path, substrate_type, substrate_fingerprint
             FROM factory_boms WHERE bom_id = ?1",
        )?;
        let mut rows = stmt.query_map(params![bom_id], |r| {
            Ok(BomRecord {
                bom_id: r.get(0)?,
                task_id: r.get(1)?,
                trace_id: r.get(2)?,
                commit_sha: r.get(3)?,
                created_at: r.get(4)?,
                bom_digest: r.get(5)?,
                signing_key_id: r.get(6)?,
                signature_b64: r.get(7)?,
                target_name: r.get(8)?,
                target_version: r.get(9)?,
                cyclonedx_path: r.get(10)?,
                slsa_path: r.get(11)?,
                canonical_path: r.get(12)?,
                substrate_type: r.get(13)?,
                substrate_fingerprint: r.get(14)?,
            })
        })?;

        if let Some(row) = rows.next() {
            Ok(Some(row?))
        } else {
            Ok(None)
        }
    }

    fn list_boms(&self, limit: usize) -> Result<Vec<BomRecord>> {
        let conn = self.conn.lock().unwrap();
        let mut stmt = conn.prepare(
            "SELECT bom_id, task_id, trace_id, commit_sha, created_at, bom_digest,
                    signing_key_id, signature_b64, target_name, target_version,
                    cyclonedx_path, slsa_path, canonical_path, substrate_type, substrate_fingerprint
             FROM factory_boms ORDER BY created_at DESC LIMIT ?1",
        )?;
        let rows = stmt.query_map(params![limit as i64], |r| {
            Ok(BomRecord {
                bom_id: r.get(0)?,
                task_id: r.get(1)?,
                trace_id: r.get(2)?,
                commit_sha: r.get(3)?,
                created_at: r.get(4)?,
                bom_digest: r.get(5)?,
                signing_key_id: r.get(6)?,
                signature_b64: r.get(7)?,
                target_name: r.get(8)?,
                target_version: r.get(9)?,
                cyclonedx_path: r.get(10)?,
                slsa_path: r.get(11)?,
                canonical_path: r.get(12)?,
                substrate_type: r.get(13)?,
                substrate_fingerprint: r.get(14)?,
            })
        })?;
        let mut list = Vec::new();
        for r in rows {
            list.push(r?);
        }
        Ok(list)
    }

    fn get_bom_by_commit(&self, commit_sha: &str) -> Result<Option<BomRecord>> {
        let conn = self.conn.lock().unwrap();
        let mut stmt = conn.prepare(
            "SELECT bom_id, task_id, trace_id, commit_sha, created_at, bom_digest,
                    signing_key_id, signature_b64, target_name, target_version,
                    cyclonedx_path, slsa_path, canonical_path, substrate_type, substrate_fingerprint
             FROM factory_boms WHERE commit_sha = ?1 ORDER BY created_at DESC LIMIT 1",
        )?;
        let mut rows = stmt.query_map(params![commit_sha], |r| {
            Ok(BomRecord {
                bom_id: r.get(0)?,
                task_id: r.get(1)?,
                trace_id: r.get(2)?,
                commit_sha: r.get(3)?,
                created_at: r.get(4)?,
                bom_digest: r.get(5)?,
                signing_key_id: r.get(6)?,
                signature_b64: r.get(7)?,
                target_name: r.get(8)?,
                target_version: r.get(9)?,
                cyclonedx_path: r.get(10)?,
                slsa_path: r.get(11)?,
                canonical_path: r.get(12)?,
                substrate_type: r.get(13)?,
                substrate_fingerprint: r.get(14)?,
            })
        })?;

        if let Some(row) = rows.next() {
            Ok(Some(row?))
        } else {
            Ok(None)
        }
    }

    fn get_bom_materials(&self, bom_id: &str) -> Result<Vec<BomMaterialRecord>> {
        let conn = self.conn.lock().unwrap();
        let mut stmt = conn.prepare(
            "SELECT material_id, bom_id, plane, category, name, version, hash, details_json
             FROM bom_materials WHERE bom_id = ?1 ORDER BY material_id ASC",
        )?;
        let rows = stmt.query_map(params![bom_id], |r| {
            Ok(BomMaterialRecord {
                material_id: r.get(0)?,
                bom_id: r.get(1)?,
                plane: r.get(2)?,
                category: r.get(3)?,
                name: r.get(4)?,
                version: r.get(5)?,
                hash: r.get(6)?,
                details_json: r.get(7)?,
            })
        })?;
        let mut list = Vec::new();
        for r in rows {
            list.push(r?);
        }
        Ok(list)
    }

    fn get_bom_artifacts(&self, bom_id: &str) -> Result<Vec<BomArtifactRecord>> {
        let conn = self.conn.lock().unwrap();
        let mut stmt = conn.prepare(
            "SELECT artifact_id, bom_id, name, path, sha256, sha512, size_bytes, mime_type
             FROM bom_artifacts WHERE bom_id = ?1 ORDER BY artifact_id ASC",
        )?;
        let rows = stmt.query_map(params![bom_id], |r| {
            Ok(BomArtifactRecord {
                artifact_id: r.get(0)?,
                bom_id: r.get(1)?,
                name: r.get(2)?,
                path: r.get(3)?,
                sha256: r.get(4)?,
                sha512: r.get(5)?,
                size_bytes: r.get::<_, i64>(6)? as u64,
                mime_type: r.get(7)?,
            })
        })?;
        let mut list = Vec::new();
        for r in rows {
            list.push(r?);
        }
        Ok(list)
    }

    fn enqueue_task(&self, task: &QueuedTask) -> Result<()> {
        let conn = self.conn.lock().unwrap();
        let reqs_json = serde_json::to_string(&task.req_ids).unwrap_or_else(|_| "[]".to_string());
        let krs_json = serde_json::to_string(&task.kr_ids).unwrap_or_else(|_| "[]".to_string());

        conn.execute(
            "INSERT INTO task_queue (
                task_id, role, req_ids, kr_ids, priority, status, attempt_count,
                model_tier, assigned_uid, proxy_port, lease_expires_at, failure_context,
                created_at, updated_at
            ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14)
            ON CONFLICT(task_id) DO UPDATE SET
                priority = excluded.priority,
                status = excluded.status,
                attempt_count = excluded.attempt_count,
                model_tier = excluded.model_tier,
                assigned_uid = excluded.assigned_uid,
                proxy_port = excluded.proxy_port,
                lease_expires_at = excluded.lease_expires_at,
                failure_context = excluded.failure_context,
                updated_at = excluded.updated_at;",
            params![
                task.task_id,
                task.role,
                reqs_json,
                krs_json,
                task.priority,
                task.status,
                task.attempt_count,
                task.model_tier,
                task.assigned_uid,
                task.proxy_port,
                task.lease_expires_at,
                task.failure_context,
                task.created_at,
                task.updated_at
            ],
        )?;

        Ok(())
    }

    fn get_queued_task(&self, task_id: &str) -> Result<Option<QueuedTask>> {
        let conn = self.conn.lock().unwrap();
        let mut stmt = conn.prepare(
            "SELECT task_id, role, req_ids, kr_ids, priority, status, attempt_count,
                    model_tier, assigned_uid, proxy_port, lease_expires_at, failure_context,
                    created_at, updated_at
             FROM task_queue WHERE task_id = ?1",
        )?;

        let mut rows = stmt.query(params![task_id])?;
        if let Some(r) = rows.next()? {
            let req_str: String = r.get(2)?;
            let kr_str: String = r.get(3)?;
            let req_ids: Vec<String> = serde_json::from_str(&req_str).unwrap_or_default();
            let kr_ids: Vec<String> = serde_json::from_str(&kr_str).unwrap_or_default();
            return Ok(Some(QueuedTask {
                task_id: r.get(0)?,
                role: r.get(1)?,
                req_ids,
                kr_ids,
                priority: r.get(4)?,
                status: r.get(5)?,
                attempt_count: r.get::<_, i64>(6)? as u32,
                model_tier: r.get(7)?,
                assigned_uid: r.get::<_, Option<i64>>(8)?.map(|v| v as u32),
                proxy_port: r.get::<_, Option<i64>>(9)?.map(|v| v as u16),
                lease_expires_at: r.get(10)?,
                failure_context: r.get(11)?,
                created_at: r.get(12)?,
                updated_at: r.get(13)?,
            }));
        }

        Ok(None)
    }

    fn list_queued_tasks(&self, status: Option<&str>, limit: usize) -> Result<Vec<QueuedTask>> {
        let conn = self.conn.lock().unwrap();
        let mut tasks = Vec::new();

        if let Some(st) = status {
            let mut stmt = conn.prepare(
                "SELECT task_id, role, req_ids, kr_ids, priority, status, attempt_count,
                        model_tier, assigned_uid, proxy_port, lease_expires_at, failure_context,
                        created_at, updated_at
                 FROM task_queue WHERE status = ?1 ORDER BY priority ASC, created_at ASC LIMIT ?2",
            )?;
            let rows = stmt.query_map(params![st, limit as i64], |r| {
                let req_str: String = r.get(2)?;
                let kr_str: String = r.get(3)?;
                Ok((
                    r.get::<_, String>(0)?,
                    r.get::<_, String>(1)?,
                    req_str,
                    kr_str,
                    r.get::<_, i32>(4)?,
                    r.get::<_, String>(5)?,
                    r.get::<_, i64>(6)? as u32,
                    r.get::<_, String>(7)?,
                    r.get::<_, Option<i64>>(8)?.map(|v| v as u32),
                    r.get::<_, Option<i64>>(9)?.map(|v| v as u16),
                    r.get::<_, Option<i64>>(10)?,
                    r.get::<_, Option<String>>(11)?,
                    r.get::<_, String>(12)?,
                    r.get::<_, String>(13)?,
                ))
            })?;

            for r in rows {
                let row = r?;
                tasks.push(QueuedTask {
                    task_id: row.0,
                    role: row.1,
                    req_ids: serde_json::from_str(&row.2).unwrap_or_default(),
                    kr_ids: serde_json::from_str(&row.3).unwrap_or_default(),
                    priority: row.4,
                    status: row.5,
                    attempt_count: row.6,
                    model_tier: row.7,
                    assigned_uid: row.8,
                    proxy_port: row.9,
                    lease_expires_at: row.10,
                    failure_context: row.11,
                    created_at: row.12,
                    updated_at: row.13,
                });
            }
        } else {
            let mut stmt = conn.prepare(
                "SELECT task_id, role, req_ids, kr_ids, priority, status, attempt_count,
                        model_tier, assigned_uid, proxy_port, lease_expires_at, failure_context,
                        created_at, updated_at
                 FROM task_queue ORDER BY priority ASC, created_at ASC LIMIT ?1",
            )?;
            let rows = stmt.query_map(params![limit as i64], |r| {
                let req_str: String = r.get(2)?;
                let kr_str: String = r.get(3)?;
                Ok((
                    r.get::<_, String>(0)?,
                    r.get::<_, String>(1)?,
                    req_str,
                    kr_str,
                    r.get::<_, i32>(4)?,
                    r.get::<_, String>(5)?,
                    r.get::<_, i64>(6)? as u32,
                    r.get::<_, String>(7)?,
                    r.get::<_, Option<i64>>(8)?.map(|v| v as u32),
                    r.get::<_, Option<i64>>(9)?.map(|v| v as u16),
                    r.get::<_, Option<i64>>(10)?,
                    r.get::<_, Option<String>>(11)?,
                    r.get::<_, String>(12)?,
                    r.get::<_, String>(13)?,
                ))
            })?;

            for r in rows {
                let row = r?;
                tasks.push(QueuedTask {
                    task_id: row.0,
                    role: row.1,
                    req_ids: serde_json::from_str(&row.2).unwrap_or_default(),
                    kr_ids: serde_json::from_str(&row.3).unwrap_or_default(),
                    priority: row.4,
                    status: row.5,
                    attempt_count: row.6,
                    model_tier: row.7,
                    assigned_uid: row.8,
                    proxy_port: row.9,
                    lease_expires_at: row.10,
                    failure_context: row.11,
                    created_at: row.12,
                    updated_at: row.13,
                });
            }
        }

        Ok(tasks)
    }

    fn peek_next_task(
        &self,
        allowed_roles: &[String],
        skip_roles: &[String],
    ) -> Result<Option<QueuedTask>> {
        let conn = self.conn.lock().unwrap();
        let mut stmt = conn.prepare(
            "SELECT task_id, role, req_ids, kr_ids, priority, status, attempt_count,
                    model_tier, assigned_uid, proxy_port, lease_expires_at, failure_context,
                    created_at, updated_at
             FROM task_queue
             WHERE status IN ('queued', 'retrying')
             ORDER BY priority ASC, created_at ASC",
        )?;

        let rows = stmt.query_map([], |r| {
            let req_str: String = r.get(2)?;
            let kr_str: String = r.get(3)?;
            Ok((
                r.get::<_, String>(0)?,
                r.get::<_, String>(1)?,
                req_str,
                kr_str,
                r.get::<_, i32>(4)?,
                r.get::<_, String>(5)?,
                r.get::<_, i64>(6)? as u32,
                r.get::<_, String>(7)?,
                r.get::<_, Option<i64>>(8)?.map(|v| v as u32),
                r.get::<_, Option<i64>>(9)?.map(|v| v as u16),
                r.get::<_, Option<i64>>(10)?,
                r.get::<_, Option<String>>(11)?,
                r.get::<_, String>(12)?,
                r.get::<_, String>(13)?,
            ))
        })?;

        for r in rows {
            let row = r?;
            let role = &row.1;

            if !allowed_roles.is_empty()
                && !allowed_roles.iter().any(|ar| ar.eq_ignore_ascii_case(role))
            {
                continue;
            }
            if !skip_roles.is_empty() && skip_roles.iter().any(|sr| sr.eq_ignore_ascii_case(role)) {
                continue;
            }

            return Ok(Some(QueuedTask {
                task_id: row.0,
                role: row.1,
                req_ids: serde_json::from_str(&row.2).unwrap_or_default(),
                kr_ids: serde_json::from_str(&row.3).unwrap_or_default(),
                priority: row.4,
                status: row.5,
                attempt_count: row.6,
                model_tier: row.7,
                assigned_uid: row.8,
                proxy_port: row.9,
                lease_expires_at: row.10,
                failure_context: row.11,
                created_at: row.12,
                updated_at: row.13,
            }));
        }

        Ok(None)
    }

    fn claim_task_lease(
        &self,
        task_id: &str,
        slot_id: usize,
        uid: u32,
        proxy_port: u16,
        lease_duration_sec: u64,
    ) -> Result<bool> {
        let conn = self.conn.lock().unwrap();
        let now_sec = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or(0) as i64;
        let expires_sec = now_sec + lease_duration_sec as i64;

        let slot_occupied: bool = conn
            .query_row(
                "SELECT task_id IS NOT NULL FROM worker_leases WHERE slot_id = ?1",
                params![slot_id as i64],
                |r| r.get(0),
            )
            .unwrap_or(true);

        if slot_occupied {
            return Ok(false);
        }

        conn.execute(
            "UPDATE worker_leases
             SET task_id = ?1, leased_at = ?2, expires_at = ?3
             WHERE slot_id = ?4",
            params![task_id, now_sec, expires_sec, slot_id as i64],
        )?;

        conn.execute(
            "UPDATE task_queue
             SET status = 'running', assigned_uid = ?1, proxy_port = ?2,
                 lease_expires_at = ?3, updated_at = ?4
             WHERE task_id = ?5",
            params![uid, proxy_port, expires_sec, now_sec.to_string(), task_id],
        )?;

        Ok(true)
    }

    fn release_task_lease(&self, slot_id: usize) -> Result<()> {
        let conn = self.conn.lock().unwrap();
        conn.execute(
            "UPDATE worker_leases
             SET task_id = NULL, leased_at = NULL, expires_at = NULL
             WHERE slot_id = ?1",
            params![slot_id as i64],
        )?;
        Ok(())
    }

    fn update_queued_task_status(
        &self,
        task_id: &str,
        status: &str,
        failure_context: Option<&str>,
    ) -> Result<()> {
        let conn = self.conn.lock().unwrap();
        let now_sec = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or(0) as i64;

        conn.execute(
            "UPDATE task_queue
             SET status = ?1, failure_context = coalesce(?2, failure_context), updated_at = ?3
             WHERE task_id = ?4",
            params![status, failure_context, now_sec.to_string(), task_id],
        )?;

        if matches!(
            status,
            "completed" | "failed" | "cancelled" | "awaiting_human"
        ) {
            conn.execute(
                "UPDATE worker_leases
                 SET task_id = NULL, leased_at = NULL, expires_at = NULL
                 WHERE task_id = ?1",
                params![task_id],
            )?;
        }

        Ok(())
    }

    fn update_queued_task_attempt(
        &self,
        task_id: &str,
        attempt_count: u32,
        model_tier: &str,
        failure_context: Option<&str>,
    ) -> Result<()> {
        let conn = self.conn.lock().unwrap();
        let now_sec = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or(0) as i64;

        conn.execute(
            "UPDATE task_queue
             SET attempt_count = ?1, model_tier = ?2, failure_context = ?3,
                 status = 'retrying', updated_at = ?4
             WHERE task_id = ?5",
            params![
                attempt_count,
                model_tier,
                failure_context,
                now_sec.to_string(),
                task_id
            ],
        )?;

        conn.execute(
            "UPDATE worker_leases
             SET task_id = NULL, leased_at = NULL, expires_at = NULL
             WHERE task_id = ?1",
            params![task_id],
        )?;

        Ok(())
    }

    fn reclaim_expired_leases(&self) -> Result<Vec<String>> {
        let conn = self.conn.lock().unwrap();
        let now_sec = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or(0) as i64;

        let mut stmt = conn.prepare(
            "SELECT slot_id, task_id
             FROM worker_leases
             WHERE task_id IS NOT NULL AND expires_at IS NOT NULL AND expires_at <= ?1",
        )?;

        let expired: Vec<(i64, String)> = stmt
            .query_map(params![now_sec], |r| Ok((r.get(0)?, r.get(1)?)))?
            .filter_map(|res| res.ok())
            .collect();

        let mut reclaimed = Vec::new();
        for (slot_id, task_id) in expired {
            conn.execute(
                "UPDATE worker_leases
                 SET task_id = NULL, leased_at = NULL, expires_at = NULL
                 WHERE slot_id = ?1",
                params![slot_id],
            )?;
            conn.execute(
                "UPDATE task_queue
                 SET status = 'retrying', updated_at = ?1
                 WHERE task_id = ?2 AND status = 'running'",
                params![now_sec.to_string(), task_id],
            )?;
            reclaimed.push(task_id);
        }

        Ok(reclaimed)
    }

    fn list_worker_leases(&self) -> Result<Vec<WorkerLeaseRecord>> {
        let conn = self.conn.lock().unwrap();
        let mut stmt = conn.prepare(
            "SELECT slot_id, uid, proxy_port, task_id, leased_at, expires_at
             FROM worker_leases ORDER BY slot_id ASC",
        )?;

        let rows = stmt.query_map([], |r| {
            Ok(WorkerLeaseRecord {
                slot_id: r.get::<_, i64>(0)? as usize,
                uid: r.get::<_, i64>(1)? as u32,
                proxy_port: r.get::<_, i64>(2)? as u16,
                task_id: r.get(3)?,
                leased_at: r.get(4)?,
                expires_at: r.get(5)?,
            })
        })?;

        let mut list = Vec::new();
        for r in rows {
            list.push(r?);
        }
        Ok(list)
    }

    fn init_worker_slots(
        &self,
        max_concurrent: usize,
        uid_start: u32,
        port_start: u16,
    ) -> Result<()> {
        let conn = self.conn.lock().unwrap();
        for i in 0..max_concurrent {
            let slot_id = i as i64;
            let uid = (uid_start + i as u32) as i64;
            let port = (port_start + i as u16) as i64;
            conn.execute(
                "INSERT INTO worker_leases (slot_id, uid, proxy_port, task_id, leased_at, expires_at)
                 VALUES (?1, ?2, ?3, NULL, NULL, NULL)
                 ON CONFLICT(slot_id) DO UPDATE SET
                     uid = excluded.uid,
                     proxy_port = excluded.proxy_port;",
                params![slot_id, uid, port],
            )?;
        }
        Ok(())
    }

    fn get_model_tier_stats(
        &self,
        role: Option<&str>,
        model_tier: &str,
    ) -> Result<(usize, f64, f64)> {
        let conn = self.conn.lock().unwrap();
        let mut stmt = conn.prepare(
            "SELECT status FROM tasks
             WHERE (?1 IS NULL OR agent_role = ?1)
               AND (model LIKE '%' || ?2 || '%')",
        )?;

        let rows = stmt.query_map(params![role, model_tier], |r| r.get::<_, String>(0))?;
        let mut total = 0;
        let mut success = 0;
        let mut failed = 0;

        for r in rows.flatten() {
            total += 1;
            if r == "verified" || r == "completed" {
                success += 1;
            } else if r == "failed" {
                failed += 1;
            }
        }

        if total == 0 {
            return Ok((0, 1.0, 0.0));
        }

        let fpy = success as f64 / total as f64;
        let cfr = failed as f64 / total as f64;
        Ok((total, fpy, cfr))
    }

    fn insert_eval_result(&self, record: &EvalResultRecord) -> Result<()> {
        let conn = self.conn.lock().unwrap();
        conn.execute(
            "INSERT OR REPLACE INTO eval_results (
                eval_id, task_id, trace_id, rubric_id, stage, judge_model,
                score, confidence, passed, escalated, rationale, checklist_json,
                cost_usd, evaluated_at
            ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14)",
            params![
                record.eval_id,
                record.task_id,
                record.trace_id,
                record.rubric_id,
                record.stage,
                record.judge_model,
                record.score,
                record.confidence,
                if record.passed { 1 } else { 0 },
                if record.escalated { 1 } else { 0 },
                record.rationale,
                record.checklist_json,
                record.cost_usd,
                record.evaluated_at,
            ],
        )?;
        Ok(())
    }

    fn get_task_evals(&self, task_id: &str) -> Result<Vec<EvalResultRecord>> {
        let conn = self.conn.lock().unwrap();
        let mut stmt = conn.prepare(
            "SELECT eval_id, task_id, trace_id, rubric_id, stage, judge_model,
                    score, confidence, passed, escalated, rationale, checklist_json,
                    cost_usd, evaluated_at
             FROM eval_results
             WHERE task_id = ?1
             ORDER BY evaluated_at ASC",
        )?;
        let rows = stmt.query_map(params![task_id], |row| {
            Ok(EvalResultRecord {
                eval_id: row.get(0)?,
                task_id: row.get(1)?,
                trace_id: row.get(2)?,
                rubric_id: row.get(3)?,
                stage: row.get(4)?,
                judge_model: row.get(5)?,
                score: row.get(6)?,
                confidence: row.get(7)?,
                passed: row.get::<_, i64>(8)? != 0,
                escalated: row.get::<_, i64>(9)? != 0,
                rationale: row.get(10)?,
                checklist_json: row.get(11)?,
                cost_usd: row.get(12)?,
                evaluated_at: row.get(13)?,
            })
        })?;
        let mut results = Vec::new();
        for r in rows {
            results.push(r?);
        }
        Ok(results)
    }

    fn get_rolling_eval_score(
        &self,
        window_days: u32,
        rubric_id: Option<&str>,
        model: Option<&str>,
    ) -> Result<f64> {
        let conn = self.conn.lock().unwrap();
        let now_sec = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or(0) as i64;
        let cutoff_sec = if window_days > 0 {
            Some(now_sec - (window_days as i64 * 86400))
        } else {
            None
        };

        let mut stmt = conn.prepare(
            "SELECT score, evaluated_at, rubric_id, judge_model
             FROM eval_results",
        )?;

        let rows = stmt.query_map([], |row| {
            let score: f64 = row.get(0)?;
            let evaluated_at: String = row.get(1)?;
            let r_id: String = row.get(2)?;
            let j_model: String = row.get(3)?;
            Ok((score, evaluated_at, r_id, j_model))
        })?;

        let mut count = 0;
        let mut sum_score = 0.0;
        for r in rows {
            let (score, evaluated_at, r_id, j_model) = r?;
            if let Some(cutoff) = cutoff_sec {
                if let Some(ts_sec) = parse_timestamp_epoch_sec(&evaluated_at) {
                    if ts_sec < cutoff {
                        continue;
                    }
                }
            }
            if let Some(target_rubric) = rubric_id {
                if r_id != target_rubric {
                    continue;
                }
            }
            if let Some(target_model) = model {
                if j_model != target_model {
                    continue;
                }
            }
            count += 1;
            sum_score += score;
        }

        if count == 0 {
            Ok(1.0)
        } else {
            Ok(sum_score / count as f64)
        }
    }

    fn get_eval_summary(&self, window_days: u32) -> Result<EvalSummaryReport> {
        let conn = self.conn.lock().unwrap();
        let now_sec = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or(0) as i64;
        let cutoff_sec = if window_days > 0 {
            Some(now_sec - (window_days as i64 * 86400))
        } else {
            None
        };

        let mut stmt = conn.prepare(
            "SELECT eval_id, task_id, rubric_id, stage, judge_model,
                    score, confidence, passed, escalated, cost_usd, evaluated_at
             FROM eval_results
             ORDER BY evaluated_at DESC",
        )?;

        let rows = stmt.query_map([], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, String>(2)?,
                row.get::<_, String>(3)?,
                row.get::<_, String>(4)?,
                row.get::<_, f64>(5)?,
                row.get::<_, f64>(6)?,
                row.get::<_, i64>(7)? != 0,
                row.get::<_, i64>(8)? != 0,
                row.get::<_, f64>(9)?,
                row.get::<_, String>(10)?,
            ))
        })?;

        let mut total_evals = 0;
        let mut passed_count = 0;
        let mut total_score = 0.0;
        let mut total_confidence = 0.0;
        let mut escalated_count = 0;
        let mut total_cost = 0.0;

        let mut by_rubric: HashMap<String, (usize, usize, f64)> = HashMap::new();
        let mut by_model: HashMap<String, (usize, usize, f64)> = HashMap::new();

        for r in rows {
            let (
                _eid,
                _tid,
                rubric_id,
                _stage,
                judge_model,
                score,
                confidence,
                passed,
                escalated,
                cost,
                evaluated_at,
            ) = r?;
            if let Some(cutoff) = cutoff_sec {
                if let Some(ts_sec) = parse_timestamp_epoch_sec(&evaluated_at) {
                    if ts_sec < cutoff {
                        continue;
                    }
                }
            }

            total_evals += 1;
            if passed {
                passed_count += 1;
            }
            if escalated {
                escalated_count += 1;
            }
            total_score += score;
            total_confidence += confidence;
            total_cost += cost;

            let r_entry = by_rubric.entry(rubric_id).or_insert((0, 0, 0.0));
            r_entry.0 += 1;
            if passed {
                r_entry.1 += 1;
            }
            r_entry.2 += score;

            let m_entry = by_model.entry(judge_model).or_insert((0, 0, 0.0));
            m_entry.0 += 1;
            if passed {
                m_entry.1 += 1;
            }
            m_entry.2 += score;
        }

        let pass_rate = if total_evals > 0 {
            passed_count as f64 / total_evals as f64
        } else {
            1.0
        };
        let mean_score = if total_evals > 0 {
            total_score / total_evals as f64
        } else {
            1.0
        };
        let mean_confidence = if total_evals > 0 {
            total_confidence / total_evals as f64
        } else {
            1.0
        };
        let escalation_rate = if total_evals > 0 {
            escalated_count as f64 / total_evals as f64
        } else {
            0.0
        };

        let rubric_stats = by_rubric
            .into_iter()
            .map(|(k, (cnt, pass, sum_s))| {
                (
                    k,
                    RubricSummaryStat {
                        count: cnt,
                        passed: pass,
                        mean_score: if cnt > 0 { sum_s / cnt as f64 } else { 0.0 },
                    },
                )
            })
            .collect();

        let model_stats = by_model
            .into_iter()
            .map(|(k, (cnt, pass, sum_s))| {
                (
                    k,
                    ModelSummaryStat {
                        count: cnt,
                        passed: pass,
                        mean_score: if cnt > 0 { sum_s / cnt as f64 } else { 0.0 },
                    },
                )
            })
            .collect();

        Ok(EvalSummaryReport {
            total_evals,
            passed_count,
            pass_rate,
            mean_score,
            mean_confidence,
            escalation_rate,
            total_cost_usd: total_cost,
            by_rubric: rubric_stats,
            by_model: model_stats,
        })
    }

    fn record_optimization_event(&self, record: &OptimizationEventRecord) -> Result<()> {
        let conn = self.conn.lock().unwrap();
        conn.execute(
            "INSERT INTO optimization_events (
                event_id, signal_tier, trigger_kind, fingerprint, details_json, action_taken, linked_task_id, created_at
            ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)
            ON CONFLICT(event_id) DO UPDATE SET
                signal_tier = excluded.signal_tier,
                trigger_kind = excluded.trigger_kind,
                fingerprint = excluded.fingerprint,
                details_json = excluded.details_json,
                action_taken = excluded.action_taken,
                linked_task_id = excluded.linked_task_id,
                created_at = excluded.created_at;",
            params![
                record.event_id,
                record.signal_tier,
                record.trigger_kind,
                record.fingerprint,
                record.details_json,
                record.action_taken,
                record.linked_task_id,
                record.created_at,
            ],
        )?;
        Ok(())
    }

    fn has_recent_optimization_event(
        &self,
        fingerprint: &str,
        cooldown_hours: u32,
    ) -> Result<bool> {
        let conn = self.conn.lock().unwrap();
        if cooldown_hours == 0 {
            return Ok(false);
        }
        let now_sec = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or(0) as i64;
        let cutoff_sec = now_sec - (cooldown_hours as i64 * 3600);

        let mut stmt = conn.prepare(
            "SELECT created_at FROM optimization_events WHERE fingerprint = ?1 ORDER BY created_at DESC",
        )?;
        let rows = stmt.query_map(params![fingerprint], |row| row.get::<_, String>(0))?;
        for created_at_res in rows {
            let created_at = created_at_res?;
            if let Some(sec) = parse_timestamp_epoch_sec(&created_at) {
                if sec >= cutoff_sec {
                    return Ok(true);
                }
            } else {
                return Ok(true);
            }
        }
        Ok(false)
    }

    fn list_optimization_events(&self, limit: usize) -> Result<Vec<OptimizationEventRecord>> {
        let conn = self.conn.lock().unwrap();
        let mut stmt = conn.prepare(
            "SELECT event_id, signal_tier, trigger_kind, fingerprint, details_json, action_taken, linked_task_id, created_at
             FROM optimization_events
             ORDER BY created_at DESC
             LIMIT ?1",
        )?;
        let rows = stmt.query_map(params![limit as i64], |row| {
            Ok(OptimizationEventRecord {
                event_id: row.get(0)?,
                signal_tier: row.get(1)?,
                trigger_kind: row.get(2)?,
                fingerprint: row.get(3)?,
                details_json: row.get(4)?,
                action_taken: row.get(5)?,
                linked_task_id: row.get(6)?,
                created_at: row.get(7)?,
            })
        })?;
        let mut out = Vec::new();
        for r in rows {
            out.push(r?);
        }
        Ok(out)
    }

    fn detect_recurring_failure_classes(
        &self,
        window_days: u32,
        min_count: usize,
    ) -> Result<Vec<RecurringFailureClassRecord>> {
        let conn = self.conn.lock().unwrap();
        let now_sec = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or(0) as i64;
        let cutoff_sec = if window_days > 0 {
            Some(now_sec - (window_days as i64 * 86400))
        } else {
            None
        };

        let mut aggregated: HashMap<(String, String), (usize, Vec<String>)> = HashMap::new();

        // 1. Query prod_signals
        let mut stmt_prod = conn.prepare(
            "SELECT signal_id, task_id, environment, observed_at, failure_class
             FROM prod_signals
             WHERE failure_class IS NOT NULL AND trim(failure_class) != ''",
        )?;
        let prod_rows = stmt_prod.query_map([], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, Option<String>>(1)?,
                row.get::<_, String>(2)?,
                row.get::<_, String>(3)?,
                row.get::<_, String>(4)?,
            ))
        })?;

        for r in prod_rows {
            let (signal_id, task_id, env, observed_at, failure_class) = r?;
            if let Some(cutoff) = cutoff_sec {
                if let Some(ts_sec) = parse_timestamp_epoch_sec(&observed_at) {
                    if ts_sec < cutoff {
                        continue;
                    }
                }
            }
            let tier = match env.to_lowercase().as_str() {
                "local" | "vcs" | "ci" | "test" => "tier1_local_vcs",
                _ => "tier2_prod",
            }
            .to_string();

            let entry = aggregated
                .entry((failure_class, tier))
                .or_insert((0, Vec::new()));
            entry.0 += 1;
            let id = task_id.unwrap_or(signal_id);
            if !entry.1.contains(&id) && entry.1.len() < 10 {
                entry.1.push(id);
            }
        }

        // 2. Query failed tasks in task_queue with failure_context
        let mut stmt_queue = conn.prepare(
            "SELECT task_id, failure_context, updated_at
             FROM task_queue
             WHERE status = 'failed' AND failure_context IS NOT NULL AND trim(failure_context) != ''",
        )?;
        let queue_rows = stmt_queue.query_map([], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, String>(2)?,
            ))
        })?;

        for r in queue_rows {
            let (task_id, failure_context, updated_at) = r?;
            if let Some(cutoff) = cutoff_sec {
                if let Some(ts_sec) = parse_timestamp_epoch_sec(&updated_at) {
                    if ts_sec < cutoff {
                        continue;
                    }
                }
            }

            let failure_class =
                if let Ok(val) = serde_json::from_str::<serde_json::Value>(&failure_context) {
                    val.get("failure_class")
                        .and_then(|v| v.as_str())
                        .map(|s| s.to_string())
                } else {
                    failure_context
                        .strip_prefix("failure_class:")
                        .map(|stripped| {
                            stripped
                                .split([' ', '\n', ';', ','])
                                .next()
                                .unwrap_or("")
                                .trim()
                                .to_string()
                        })
                };

            if let Some(fc) = failure_class {
                if !fc.is_empty() {
                    let entry = aggregated
                        .entry((fc, "tier1_local_vcs".to_string()))
                        .or_insert((0, Vec::new()));
                    entry.0 += 1;
                    if !entry.1.contains(&task_id) && entry.1.len() < 10 {
                        entry.1.push(task_id);
                    }
                }
            }
        }

        let mut results = Vec::new();
        for ((failure_class, signal_tier), (count, sample_ids)) in aggregated {
            if count >= min_count {
                results.push(RecurringFailureClassRecord {
                    failure_class,
                    count,
                    signal_tier,
                    sample_ids,
                });
            }
        }

        results.sort_by_key(|a| std::cmp::Reverse(a.count));
        Ok(results)
    }
}

pub fn get_analytics_store(db_path: &Path) -> Result<Box<dyn FactoryAnalyticsStore>> {
    let store = SqliteAnalyticsStore::open_or_create(db_path)?;
    Ok(Box::new(store))
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn test_sqlite_analytics_store_lifecycle() {
        let td = tempdir().unwrap();
        let db_path = td.path().join("factory.db");

        let store = SqliteAnalyticsStore::open_or_create(&db_path).unwrap();

        let mut ctx = TaskContext::new("feat-auth-001");
        ctx.objective_id = Some("OBJ-2026-Q4-SEC".to_string());
        ctx.kr_ids = vec!["KR-AUTH-01".to_string()];
        ctx.req_ids = vec!["REQ-TOKEN-ROTATION".to_string()];
        ctx.agent_role = Some("design_engineer".to_string());
        ctx.cost_usd = Some(0.12);

        store.record_task(&ctx, "in_progress").unwrap();

        let loaded = store.get_task("feat-auth-001").unwrap().unwrap();
        assert_eq!(loaded.task_id, "feat-auth-001");
        assert_eq!(loaded.objective_id.as_deref(), Some("OBJ-2026-Q4-SEC"));
        assert_eq!(loaded.kr_ids, vec!["KR-AUTH-01"]);
        assert_eq!(loaded.req_ids, vec!["REQ-TOKEN-ROTATION"]);
        assert_eq!(loaded.status, "in_progress");

        // Update status and cost
        ctx.cost_usd = Some(0.25);
        store.record_task(&ctx, "completed").unwrap();
        let updated = store.get_task("feat-auth-001").unwrap().unwrap();
        assert_eq!(updated.status, "completed");
        assert_eq!(updated.cost_usd, Some(0.25));

        // Record traceability report
        let report = TraceabilityReport {
            engine: "openfasttrace".to_string(),
            total_requirements: 2,
            covered_requirements: 2,
            missing_impl: Vec::new(),
            missing_tests: Vec::new(),
            coverage_pct: 100.0,
            is_compliant: true,
            details: std::collections::HashMap::new(),
            ..TraceabilityReport::empty("openfasttrace")
        };
        store.record_traceability("feat-auth-001", &report).unwrap();

        // Record VCS outcome
        store
            .record_vcs_outcome("feat-auth-001", "abc1234", true)
            .unwrap();

        // List tasks
        let list = store.list_tasks(10).unwrap();
        assert_eq!(list.len(), 1);
        assert_eq!(list[0].task_id, "feat-auth-001");
    }

    #[test]
    fn test_dora_and_flow_aggregations() {
        let td = tempdir().unwrap();
        let db_path = td.path().join("factory.db");
        let store = SqliteAnalyticsStore::open_or_create(&db_path).unwrap();

        // Seed 10 tasks
        for i in 1..=10 {
            let task_id = format!("task-{:03}", i);
            let mut ctx = TaskContext::new(&task_id);
            ctx.agent_role = Some(
                if i <= 5 {
                    "implementer"
                } else {
                    "test_engineer"
                }
                .to_string(),
            );
            ctx.model_profile = Some(if i <= 5 { "claude" } else { "gemini" }.to_string());
            ctx.objective_id = Some("OBJ-CORE-1".to_string());
            ctx.cost_usd = Some(10.0);
            store.record_task(&ctx, "verified").unwrap();
        }

        // 8 Merged PRs:
        // - 6 first-pass (rounds=0, commits=0, ci_failed=false, reverted=false)
        for i in 1..=6 {
            let record = VcsOutcomeRecord {
                pr_id: format!("pr-{}", i),
                task_id: Some(format!("task-{:03}", i)),
                repo: "org/repo".to_string(),
                pr_number: i as u64,
                state: "merged".to_string(),
                opened_at: "1000".to_string(),
                first_review_at: Some("1100".to_string()),
                merged_at: Some("1500".to_string()),
                human_review_rounds: 0,
                human_commits_added: 0,
                ci_runs_count: 1,
                ci_failed_first_run: false,
                reverted: false,
                lead_time_sec: Some(500.0),
                synced_at: "1600".to_string(),
            };
            store.upsert_vcs_outcome(&record).unwrap();
        }

        // - 1 with review rounds
        let pr7 = VcsOutcomeRecord {
            pr_id: "pr-7".to_string(),
            task_id: Some("task-007".to_string()),
            repo: "org/repo".to_string(),
            pr_number: 7,
            state: "merged".to_string(),
            opened_at: "1000".to_string(),
            first_review_at: Some("1100".to_string()),
            merged_at: Some("2000".to_string()),
            human_review_rounds: 2,
            human_commits_added: 1,
            ci_runs_count: 2,
            ci_failed_first_run: false,
            reverted: false,
            lead_time_sec: Some(1000.0),
            synced_at: "2100".to_string(),
        };
        store.upsert_vcs_outcome(&pr7).unwrap();

        // - 1 reverted with incident
        let pr8 = VcsOutcomeRecord {
            pr_id: "pr-8".to_string(),
            task_id: Some("task-008".to_string()),
            repo: "org/repo".to_string(),
            pr_number: 8,
            state: "merged".to_string(),
            opened_at: "1000".to_string(),
            first_review_at: Some("1100".to_string()),
            merged_at: Some("2500".to_string()),
            human_review_rounds: 0,
            human_commits_added: 0,
            ci_runs_count: 1,
            ci_failed_first_run: false,
            reverted: true,
            lead_time_sec: Some(1500.0),
            synced_at: "2600".to_string(),
        };
        store.upsert_vcs_outcome(&pr8).unwrap();

        // Signal for pr8
        let sig = ProdSignalRecord {
            signal_id: "sig-1".to_string(),
            task_id: Some("task-008".to_string()),
            deploy_sha: "sha-8".to_string(),
            environment: "production".to_string(),
            observed_at: "2600".to_string(),
            error_rate_delta: 0.05,
            p95_latency_delta_ms: 120.0,
            slo_budget_burn_pct: 0.1,
            incident_triggered: true,
            mttr_sec: Some(600.0),
            failure_class: Some("crash".to_string()),
        };
        store.insert_prod_signal(&sig).unwrap();

        // 2 Open PRs (pr-9 and pr-10)
        for i in 9..=10 {
            let record = VcsOutcomeRecord {
                pr_id: format!("pr-{}", i),
                task_id: Some(format!("task-{:03}", i)),
                repo: "org/repo".to_string(),
                pr_number: i as u64,
                state: "open".to_string(),
                opened_at: "3000".to_string(),
                first_review_at: None,
                merged_at: None,
                human_review_rounds: 0,
                human_commits_added: 0,
                ci_runs_count: 1,
                ci_failed_first_run: false,
                reverted: false,
                lead_time_sec: None,
                synced_at: "3100".to_string(),
            };
            store.upsert_vcs_outcome(&record).unwrap();
        }

        let report = store.get_dora_flow_report(0, Some("role")).unwrap();

        // Assert exact metrics
        assert_eq!(report.total_merged_prs, 8);
        assert_eq!(report.open_pr_queue_depth, 2);
        assert!((report.first_pass_yield - 0.75).abs() < 1e-6); // 6 / 8 = 0.75
        assert!((report.change_failure_rate - 0.125).abs() < 1e-6); // 1 / 8 = 0.125
        assert_eq!(report.mttr_avg_sec, Some(600.0));
        assert_eq!(report.cost_per_merged_pr, Some(10.0)); // $80 total / 8 merged
        assert_eq!(report.cost_per_first_pass_pr, Some(10.0)); // $60 total / 6 first pass
        assert!(report.flow_efficiency > 0.0);

        // Assert rolling queries
        let fpy = store.get_rolling_fpy(0, None, None).unwrap();
        assert!((fpy - 0.75).abs() < 1e-6);

        let cfr = store.get_rolling_cfr(0).unwrap();
        assert!((cfr - 0.125).abs() < 1e-6);

        let queue = store.get_open_pr_count().unwrap();
        assert_eq!(queue, 2);
    }

    #[test]
    fn test_task_queue_and_worker_leases() {
        let td = tempdir().unwrap();
        let db_path = td.path().join("factory.db");
        let store = SqliteAnalyticsStore::open_or_create(&db_path).unwrap();

        // Initialize 4 worker slots (UID 2001..2004, Ports 8081..8084)
        store.init_worker_slots(4, 2001, 8081).unwrap();
        let leases = store.list_worker_leases().unwrap();
        assert_eq!(leases.len(), 4);
        assert_eq!(leases[0].uid, 2001);
        assert_eq!(leases[0].proxy_port, 8081);
        assert!(leases[0].task_id.is_none());

        // Enqueue two tasks
        let t1 = QueuedTask {
            task_id: "task-001".to_string(),
            role: "feature".to_string(),
            req_ids: vec!["REQ-1".to_string()],
            kr_ids: vec!["KR-1".to_string()],
            priority: 10,
            status: "queued".to_string(),
            attempt_count: 0,
            model_tier: "local".to_string(),
            assigned_uid: None,
            proxy_port: None,
            lease_expires_at: None,
            failure_context: None,
            created_at: "1000".to_string(),
            updated_at: "1000".to_string(),
        };
        let t2 = QueuedTask {
            task_id: "task-002".to_string(),
            role: "review_assist".to_string(),
            req_ids: vec![],
            kr_ids: vec![],
            priority: 5, // higher priority
            status: "queued".to_string(),
            attempt_count: 0,
            model_tier: "local".to_string(),
            assigned_uid: None,
            proxy_port: None,
            lease_expires_at: None,
            failure_context: None,
            created_at: "1005".to_string(),
            updated_at: "1005".to_string(),
        };
        store.enqueue_task(&t1).unwrap();
        store.enqueue_task(&t2).unwrap();

        // Peek next task without filter -> t2 has priority 5 < 10
        let peeked = store.peek_next_task(&[], &[]).unwrap().unwrap();
        assert_eq!(peeked.task_id, "task-002");

        // Peek next task with role filter -> "feature"
        let peeked_feat = store
            .peek_next_task(&["feature".to_string()], &[])
            .unwrap()
            .unwrap();
        assert_eq!(peeked_feat.task_id, "task-001");

        // Claim lease for slot 0 (UID 2001, port 8081)
        let claimed = store
            .claim_task_lease("task-002", 0, 2001, 8081, 60)
            .unwrap();
        assert!(claimed);

        // Double claim should return false
        let double_claim = store
            .claim_task_lease("task-001", 0, 2001, 8081, 60)
            .unwrap();
        assert!(!double_claim);

        // Check task status became running
        let t2_running = store.get_queued_task("task-002").unwrap().unwrap();
        assert_eq!(t2_running.status, "running");
        assert_eq!(t2_running.assigned_uid, Some(2001));
        assert_eq!(t2_running.proxy_port, Some(8081));

        // Complete task-002 -> releases lease
        store
            .update_queued_task_status("task-002", "completed", None)
            .unwrap();
        let leases_after = store.list_worker_leases().unwrap();
        assert!(leases_after[0].task_id.is_none());

        // Reclaim expired leases test: lease slot 1 with expired time (duration 0)
        let _ = store
            .claim_task_lease("task-001", 1, 2002, 8082, 0)
            .unwrap();
        let reclaimed = store.reclaim_expired_leases().unwrap();
        assert_eq!(reclaimed, vec!["task-001"]);
        let t1_retrying = store.get_queued_task("task-001").unwrap().unwrap();
        assert_eq!(t1_retrying.status, "retrying");
    }

    #[test]
    fn test_model_tier_stats() {
        let td = tempdir().unwrap();
        let db_path = td.path().join("factory.db");
        let store = SqliteAnalyticsStore::open_or_create(&db_path).unwrap();

        // 0 tasks initially
        let (sample, fpy, cfr) = store
            .get_model_tier_stats(Some("feature"), "local")
            .unwrap();
        assert_eq!(sample, 0);
        assert_eq!(fpy, 1.0);
        assert_eq!(cfr, 0.0);

        // Record 3 local tasks: 2 verified, 1 failed
        let mut c1 = TaskContext::new("t1");
        c1.agent_role = Some("feature".to_string());
        c1.model_profile = Some("llama-server:local".to_string());
        store.record_task(&c1, "verified").unwrap();

        let mut c2 = TaskContext::new("t2");
        c2.agent_role = Some("feature".to_string());
        c2.model_profile = Some("llama-server:local".to_string());
        store.record_task(&c2, "failed").unwrap();

        let mut c3 = TaskContext::new("t3");
        c3.agent_role = Some("feature".to_string());
        c3.model_profile = Some("llama-server:local".to_string());
        store.record_task(&c3, "verified").unwrap();

        let (sample, fpy, cfr) = store
            .get_model_tier_stats(Some("feature"), "local")
            .unwrap();
        assert_eq!(sample, 3);
        assert!((fpy - 2.0 / 3.0).abs() < 1e-6);
        assert!((cfr - 1.0 / 3.0).abs() < 1e-6);
    }

    #[test]
    fn test_eval_results_storage() {
        let td = tempdir().unwrap();
        let db_path = td.path().join("factory.db");
        let store = SqliteAnalyticsStore::open_or_create(&db_path).unwrap();

        let rec1 = EvalResultRecord {
            eval_id: "eval-001".to_string(),
            task_id: "task-feat-1".to_string(),
            trace_id: "trace-abc".to_string(),
            rubric_id: "spec_adherence".to_string(),
            stage: "system1".to_string(),
            judge_model: "typesafe-jev-v1".to_string(),
            score: 0.95,
            confidence: 0.90,
            passed: true,
            escalated: false,
            rationale: None,
            checklist_json: "{}".to_string(),
            cost_usd: 0.001,
            evaluated_at: "1700000000".to_string(),
        };

        let rec2 = EvalResultRecord {
            eval_id: "eval-002".to_string(),
            task_id: "task-feat-1".to_string(),
            trace_id: "trace-abc".to_string(),
            rubric_id: "security_hygiene".to_string(),
            stage: "cascade".to_string(),
            judge_model: "qwen2.5-coder-32b".to_string(),
            score: 0.60,
            confidence: 0.85,
            passed: false,
            escalated: true,
            rationale: Some("Found unescaped SQL parameter".to_string()),
            checklist_json: "{}".to_string(),
            cost_usd: 0.005,
            evaluated_at: "1700000010".to_string(),
        };

        store.insert_eval_result(&rec1).unwrap();
        store.insert_eval_result(&rec2).unwrap();

        let evals = store.get_task_evals("task-feat-1").unwrap();
        assert_eq!(evals.len(), 2);
        assert_eq!(evals[0].eval_id, "eval-001");
        assert_eq!(evals[1].eval_id, "eval-002");
        assert!(evals[0].passed);
        assert!(!evals[1].passed);
        assert!(evals[1].escalated);
        assert_eq!(
            evals[1].rationale.as_deref(),
            Some("Found unescaped SQL parameter")
        );

        let rolling_score = store
            .get_rolling_eval_score(0, Some("spec_adherence"), None)
            .unwrap();
        assert!((rolling_score - 0.95).abs() < 1e-6);

        let summary = store.get_eval_summary(0).unwrap();
        assert_eq!(summary.total_evals, 2);
        assert_eq!(summary.passed_count, 1);
        assert_eq!(summary.pass_rate, 0.5);
        assert_eq!(summary.escalation_rate, 0.5);
        assert_eq!(summary.total_cost_usd, 0.006);
        assert!(summary.by_rubric.contains_key("spec_adherence"));
        assert!(summary.by_rubric.contains_key("security_hygiene"));
    }

    #[test]
    fn test_design_gate_results_storage() {
        let temp_dir = tempdir().unwrap();
        let db_path = temp_dir.path().join("factory.db");
        let store = SqliteAnalyticsStore::open_or_create(&db_path).unwrap();

        let mut report = crate::design::DesignGateReport::empty("git_only");
        report.needs_design_review = true;
        report.new_components = vec!["CardView".to_string()];
        report.violations.push(crate::design::DesignLintViolation {
            file: "App.tsx".to_string(),
            line: 5,
            rule: "raw_primitive_violation".to_string(),
            message: "raw button".to_string(),
            severity: "warning".to_string(),
        });
        report.platform_results.insert(
            "ios".to_string(),
            crate::design::PlatformGateResult {
                platform: "ios".to_string(),
                status: "passed".to_string(),
                message: "ios active".to_string(),
                details: vec![],
            },
        );

        store
            .record_design_gate_report(Some("task-feat-design-1"), &report)
            .unwrap();

        let results = store
            .get_task_design_gate_results("task-feat-design-1")
            .unwrap();
        assert_eq!(results.len(), 1);
        assert_eq!(results[0].platform, "ios");
        assert_eq!(results[0].raw_primitive_violations, 1);
        assert_eq!(results[0].new_components_count, 1);
        assert!(results[0].needs_design_review);
        assert_eq!(results[0].status, "passed");
    }

    #[test]
    fn test_sca_gate_results_storage() {
        let temp_dir = tempdir().unwrap();
        let db_path = temp_dir.path().join("factory.db");
        let store = SqliteAnalyticsStore::open_or_create(&db_path).unwrap();

        let mut report = crate::sca::ScaGateReport::empty("cargo-audit");
        report.vulnerabilities_found = 1;
        report
            .blocking_vulnerabilities
            .push(crate::sca::ScaVulnerability {
                id: "RUSTSEC-2026-0001".to_string(),
                package: "vulnerable-pkg".to_string(),
                installed_version: "0.1.0".to_string(),
                patched_versions: vec!["0.2.0".to_string()],
                severity: crate::sca::ScaSeverity::High,
                title: "Memory safety issue".to_string(),
                url: None,
                advisory_source: "rustsec".to_string(),
            });
        report.is_compliant = false;
        report.summary = "1 blocking vulnerability detected.".to_string();

        store
            .record_sca_gate_report(Some("task-sca-1"), &report)
            .unwrap();

        let res = store.get_sca_gate_report("task-sca-1").unwrap().unwrap();
        assert_eq!(res.scanner, "cargo-audit");
        assert!(!res.is_compliant);
        assert_eq!(res.vulnerabilities_found, 1);
        assert_eq!(res.blocking_count, 1);
        assert_eq!(res.summary, "1 blocking vulnerability detected.");
    }
}
