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
    pub kr_ids: Vec<String>,
    pub req_ids: Vec<String>,
}

pub trait FactoryAnalyticsStore: Send + Sync {
    fn record_task(&self, task_ctx: &TaskContext, status: &str) -> Result<()>;
    fn record_traceability(&self, task_id: &str, report: &TraceabilityReport) -> Result<()>;
    fn record_vcs_outcome(&self, task_id: &str, commit_sha: &str, valid: bool) -> Result<()>;
    fn get_task(&self, task_id: &str) -> Result<Option<TaskRecord>>;
    fn list_tasks(&self, limit: usize) -> Result<Vec<TaskRecord>>;
    fn get_kr_spend(&self, kr_id: &str) -> Result<f64>;
    fn get_recent_success_rate(&self, limit: usize) -> Result<(usize, usize, f64)>;
    fn get_analytics_summary(&self) -> Result<AnalyticsSummary>;
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

        // Initialize WAL mode and fast synchronous settings
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
                 created_at TEXT NOT NULL
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
                 timestamp TEXT NOT NULL
             );

             CREATE TABLE IF NOT EXISTS vcs_outcomes (
                 task_id TEXT PRIMARY KEY,
                 commit_sha TEXT NOT NULL,
                 valid INTEGER NOT NULL,
                 timestamp TEXT NOT NULL
             );",
        )
        .context("Failed to initialize database tables")?;

        Ok(Self {
            conn: Mutex::new(conn),
            path: db_path.to_path_buf(),
        })
    }

    pub fn path(&self) -> &Path {
        &self.path
    }
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
                 cost_usd = excluded.cost_usd;",
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
            let _ = conn.execute(
                "INSERT OR IGNORE INTO task_krs (task_id, kr_id) VALUES (?1, ?2)",
                params![task_ctx.task_id, kr],
            );
        }

        for req in &task_ctx.req_ids {
            let _ = conn.execute(
                "INSERT OR IGNORE INTO task_reqs (task_id, req_id) VALUES (?1, ?2)",
                params![task_ctx.task_id, req],
            );
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
            "INSERT INTO traceability_reports (task_id, engine, total_reqs, covered_reqs, coverage_pct, is_compliant, timestamp)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)
             ON CONFLICT(task_id) DO UPDATE SET
                 total_reqs = excluded.total_reqs,
                 covered_reqs = excluded.covered_reqs,
                 coverage_pct = excluded.coverage_pct,
                 is_compliant = excluded.is_compliant,
                 timestamp = excluded.timestamp;",
            params![
                task_id,
                report.engine,
                report.total_requirements as i64,
                report.covered_requirements as i64,
                report.coverage_pct,
                if report.is_compliant { 1 } else { 0 },
                now_iso
            ],
        )?;

        Ok(())
    }

    fn record_vcs_outcome(&self, task_id: &str, commit_sha: &str, valid: bool) -> Result<()> {
        let conn = self.conn.lock().unwrap();
        let now_iso = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_secs().to_string())
            .unwrap_or_default();

        conn.execute(
            "INSERT INTO vcs_outcomes (task_id, commit_sha, valid, timestamp)
             VALUES (?1, ?2, ?3, ?4)
             ON CONFLICT(task_id) DO UPDATE SET
                 commit_sha = excluded.commit_sha,
                 valid = excluded.valid,
                 timestamp = excluded.timestamp;",
            params![task_id, commit_sha, if valid { 1 } else { 0 }, now_iso],
        )?;

        Ok(())
    }

    fn get_task(&self, task_id: &str) -> Result<Option<TaskRecord>> {
        let conn = self.conn.lock().unwrap();
        let mut stmt = conn.prepare(
            "SELECT task_id, trace_id, objective_id, agent_role, model, cost_usd, status, created_at
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
                kr_ids,
                req_ids,
            }));
        }

        Ok(None)
    }

    fn list_tasks(&self, limit: usize) -> Result<Vec<TaskRecord>> {
        let conn = self.conn.lock().unwrap();
        let mut stmt = conn.prepare(
            "SELECT task_id, trace_id, objective_id, agent_role, model, cost_usd, status, created_at
             FROM tasks ORDER BY created_at DESC LIMIT ?1",
        )?;

        let rows = stmt.query_map(params![limit as i64], |row| {
            Ok(TaskRecord {
                task_id: row.get(0)?,
                trace_id: row.get(1)?,
                objective_id: row.get(2)?,
                agent_role: row.get(3)?,
                model: row.get(4)?,
                cost_usd: row.get(5)?,
                status: row.get(6)?,
                created_at: row.get(7)?,
                kr_ids: Vec::new(),
                req_ids: Vec::new(),
            })
        })?;

        let mut tasks = Vec::new();
        for t in rows.filter_map(|r| r.ok()) {
            tasks.push(t);
        }
        Ok(tasks)
    }

    fn get_kr_spend(&self, kr_id: &str) -> Result<f64> {
        let conn = self.conn.lock().unwrap();
        let mut stmt = conn.prepare(
            "SELECT COALESCE(SUM(t.cost_usd), 0.0)
             FROM tasks t
             JOIN task_krs tk ON t.task_id = tk.task_id
             WHERE tk.kr_id = ?1",
        )?;
        let spend: f64 = stmt.query_row(params![kr_id], |row| row.get(0))?;
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
}
