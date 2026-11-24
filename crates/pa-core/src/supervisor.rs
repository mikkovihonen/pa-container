use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::Duration;

#[cfg(unix)]
use std::io::{BufRead, BufReader, Read, Write};
#[cfg(unix)]
use std::os::unix::net::{UnixListener, UnixStream};

use crate::governance::GovernanceEngine;
use crate::schema::FactoryConfig;
use crate::storage::{FactoryAnalyticsStore, QueuedTask, WorkerLeaseRecord};
use crate::telemetry::{ProxyBindings, TaskContext};

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct SupervisorTickSummary {
    pub active_workers: usize,
    pub idle_slots: usize,
    pub claimed_tasks: Vec<String>,
    pub reclaimed_tasks: Vec<String>,
    pub hitl_paused_tasks: Vec<String>,
    pub wip_reallocation_active: bool,
    pub slo_defense_active: bool,
    #[serde(default)]
    pub enqueued_diagnostic_tasks: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct SupervisorStatus {
    pub pid: Option<u32>,
    pub running: bool,
    pub max_concurrency: usize,
    pub active_leases: usize,
    pub idle_leases: usize,
    pub queued_tasks_count: usize,
    pub wip_reallocation_active: bool,
    pub slo_defense_active: bool,
    pub leases: Vec<WorkerLeaseRecord>,
    pub queued_tasks: Vec<QueuedTask>,
}

pub struct HostSupervisor {
    pub store: Arc<dyn FactoryAnalyticsStore>,
    pub config: FactoryConfig,
    pub workspace_root: PathBuf,
}

impl HostSupervisor {
    pub fn new(
        store: Arc<dyn FactoryAnalyticsStore>,
        config: FactoryConfig,
        workspace_root: PathBuf,
    ) -> Result<Self> {
        let sup_cfg = &config.supervisor;
        store.init_worker_slots(
            sup_cfg.max_concurrent_agents,
            sup_cfg.slot_uid_start,
            sup_cfg.slot_proxy_port_start,
        )?;
        Ok(Self {
            store,
            config,
            workspace_root,
        })
    }

    /// Execute a single scheduler tick
    pub fn tick(&self) -> Result<SupervisorTickSummary> {
        // 1. Reclaim expired leases
        let reclaimed_tasks = self.store.reclaim_expired_leases()?;

        // 2. Poll intercom message bus for mid-turn HITL pauses
        let hitl_paused_tasks = self.poll_intercom_hitl()?;

        // 3. Query GovernanceEngine for WIP limits and SLO Defense Mode
        let running_tasks = self.store.list_queued_tasks(Some("running"), 1000)?;
        let active_wip_count = running_tasks.len();
        let gov_decision = GovernanceEngine::evaluate_dispatch(
            self.store.as_ref(),
            &self.config.governance,
            active_wip_count,
            None,
            None,
        )?;

        let wip_limit_reached =
            !gov_decision.allowed && gov_decision.reason.contains("WIP limit reached");
        let slo_defense_active = gov_decision.defense_mode_active;

        let (allowed_roles, skip_roles) = if slo_defense_active {
            (
                self.config.governance.defense_mode_allowed_roles.clone(),
                Vec::new(),
            )
        } else if wip_limit_reached {
            (
                self.config.supervisor.reallocate_roles.clone(),
                vec!["feature".to_string(), "spec_architect".to_string()],
            )
        } else {
            (Vec::new(), Vec::new())
        };

        // 4. Find available idle slots
        let leases = self.store.list_worker_leases()?;
        let idle_slots: Vec<WorkerLeaseRecord> =
            leases.into_iter().filter(|l| l.task_id.is_none()).collect();
        let active_workers = self.config.supervisor.max_concurrent_agents - idle_slots.len();

        let mut claimed_tasks = Vec::new();

        // 5. Pull and dispatch tasks for idle slots
        for slot in &idle_slots {
            if let Some(task) = self.store.peek_next_task(&allowed_roles, &skip_roles)? {
                let lease_claimed = self.store.claim_task_lease(
                    &task.task_id,
                    slot.slot_id,
                    slot.uid,
                    slot.proxy_port,
                    self.config.supervisor.lease_timeout_sec,
                )?;

                if lease_claimed {
                    self.provision_worker_binding(&task, slot)?;
                    claimed_tasks.push(task.task_id);
                }
            } else {
                break;
            }
        }

        // 6. Evaluate self-optimization triggers and dispatch meta-roles
        let enqueued_diagnostic_tasks = self.dispatch_self_optimization()?;

        Ok(SupervisorTickSummary {
            active_workers: active_workers + claimed_tasks.len(),
            idle_slots: idle_slots.len().saturating_sub(claimed_tasks.len()),
            claimed_tasks,
            reclaimed_tasks,
            hitl_paused_tasks,
            wip_reallocation_active: wip_limit_reached,
            slo_defense_active,
            enqueued_diagnostic_tasks,
        })
    }

    /// Evaluate self-optimization triggers and auto-enqueue factory_diagnostician or okr_analyst
    pub fn dispatch_self_optimization(&self) -> Result<Vec<String>> {
        let gov_cfg = &self.config.governance;
        let opt_cfg = &gov_cfg.self_optimization;
        if !opt_cfg.enabled {
            return Ok(Vec::new());
        }

        let triggers = GovernanceEngine::evaluate_self_optimization(
            self.store.as_ref(),
            gov_cfg,
            Some(&self.config),
        )?;

        let mut enqueued = Vec::new();
        let now_micros = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_micros())
            .unwrap_or(0);
        let now_sec = (now_micros / 1_000_000) as u64;
        let now_iso = format!("{}", now_sec);

        for trigger in triggers {
            if opt_cfg.auto_enqueue_diagnostician
                && (trigger.trigger_kind
                    == crate::governance::OptimizationTriggerKind::FailureClass
                    || trigger.trigger_kind == crate::governance::OptimizationTriggerKind::CfrSpike
                    || trigger.trigger_kind == crate::governance::OptimizationTriggerKind::LowFpy
                    || trigger.trigger_kind
                        == crate::governance::OptimizationTriggerKind::LowEvalScore)
            {
                let task_id = format!("diag-{}-{}", trigger.trigger_kind, now_micros);
                let failure_context = serde_json::to_string(&trigger).unwrap_or_default();

                let task = QueuedTask {
                    task_id: task_id.clone(),
                    role: "factory_diagnostician".to_string(),
                    req_ids: Vec::new(),
                    kr_ids: Vec::new(),
                    priority: 90,
                    status: "pending".to_string(),
                    attempt_count: 0,
                    model_tier: "frontier".to_string(),
                    assigned_uid: None,
                    proxy_port: None,
                    lease_expires_at: None,
                    failure_context: Some(failure_context),
                    created_at: now_iso.clone(),
                    updated_at: now_iso.clone(),
                };

                self.store.enqueue_task(&task)?;

                let event = crate::storage::OptimizationEventRecord {
                    event_id: format!("enqueue:diag:{}:{}", trigger.fingerprint, now_micros),
                    signal_tier: trigger.tier.to_string(),
                    trigger_kind: trigger.trigger_kind.to_string(),
                    fingerprint: trigger.fingerprint.clone(),
                    details_json: serde_json::to_string(&trigger).unwrap_or_default(),
                    action_taken: "diagnostician_enqueued".to_string(),
                    linked_task_id: Some(task_id.clone()),
                    created_at: now_iso.clone(),
                };
                self.store.record_optimization_event(&event)?;
                enqueued.push(task_id);
            } else if opt_cfg.auto_enqueue_okr_analyst
                && trigger.trigger_kind
                    == crate::governance::OptimizationTriggerKind::KrBudgetOverrun
            {
                let task_id = format!("okr-analyst-{}", now_micros);
                let failure_context = serde_json::to_string(&trigger).unwrap_or_default();

                let task = QueuedTask {
                    task_id: task_id.clone(),
                    role: "okr_analyst".to_string(),
                    req_ids: Vec::new(),
                    kr_ids: Vec::new(),
                    priority: 85,
                    status: "pending".to_string(),
                    attempt_count: 0,
                    model_tier: "local".to_string(),
                    assigned_uid: None,
                    proxy_port: None,
                    lease_expires_at: None,
                    failure_context: Some(failure_context),
                    created_at: now_iso.clone(),
                    updated_at: now_iso.clone(),
                };

                self.store.enqueue_task(&task)?;

                let event = crate::storage::OptimizationEventRecord {
                    event_id: format!("enqueue:okr:{}:{}", trigger.fingerprint, now_micros),
                    signal_tier: trigger.tier.to_string(),
                    trigger_kind: trigger.trigger_kind.to_string(),
                    fingerprint: trigger.fingerprint.clone(),
                    details_json: serde_json::to_string(&trigger).unwrap_or_default(),
                    action_taken: "okr_brief_enqueued".to_string(),
                    linked_task_id: Some(task_id.clone()),
                    created_at: now_iso.clone(),
                };
                self.store.record_optimization_event(&event)?;
                enqueued.push(task_id);
            }
        }

        Ok(enqueued)
    }

    /// Provision proxy bindings and context for a claimed worker slot
    pub fn provision_worker_binding(
        &self,
        task: &QueuedTask,
        slot: &WorkerLeaseRecord,
    ) -> Result<()> {
        let mut task_ctx = TaskContext::new(&task.task_id);
        task_ctx.agent_role = Some(task.role.clone());
        task_ctx.model_profile = Some(task.model_tier.clone());
        task_ctx.kr_ids = task.kr_ids.clone();
        task_ctx.req_ids = task.req_ids.clone();

        let bindings_path = self.workspace_root.join(".pa/proxy-bindings.json");
        if let Some(p) = bindings_path.parent() {
            let _ = fs::create_dir_all(p);
        }
        let mut bindings = ProxyBindings::load(&bindings_path).unwrap_or_default();
        bindings.set_for_port(slot.proxy_port, task_ctx);
        let _ = bindings.save_atomic(&bindings_path);

        Ok(())
    }

    /// Poll durable agentintercom message bus for hitl_pause messages
    fn poll_intercom_hitl(&self) -> Result<Vec<String>> {
        let mut paused = Vec::new();
        let intercom_dir = &self.config.supervisor.intercom_dir;
        let bus_path = if intercom_dir.is_relative() {
            self.workspace_root.join(intercom_dir)
        } else {
            intercom_dir.clone()
        };

        let inbox_dir = bus_path.join("inbox");
        if !inbox_dir.is_dir() {
            return Ok(paused);
        }

        if let Ok(entries) = fs::read_dir(&inbox_dir) {
            for entry in entries.flatten() {
                let peer_inbox = entry.path();
                if !peer_inbox.is_dir() {
                    continue;
                }
                if let Ok(msg_files) = fs::read_dir(&peer_inbox) {
                    for mf in msg_files.flatten() {
                        let path = mf.path();
                        if path.extension().and_then(|s| s.to_str()) == Some("json") {
                            if let Ok(content) = fs::read_to_string(&path) {
                                if let Ok(val) = serde_json::from_str::<serde_json::Value>(&content)
                                {
                                    let msg_type = val.get("type").and_then(|s| s.as_str());
                                    if msg_type == Some("hitl_pause") {
                                        if let Some(task_id) =
                                            val.get("task_id").and_then(|s| s.as_str())
                                        {
                                            let prompt = val
                                                .get("prompt")
                                                .and_then(|s| s.as_str())
                                                .unwrap_or("Human review requested");
                                            let _ = self.store.update_queued_task_status(
                                                task_id,
                                                "awaiting_human",
                                                Some(prompt),
                                            );
                                            paused.push(task_id.to_string());
                                            let _ = fs::remove_file(&path);
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        Ok(paused)
    }

    /// Query full status of supervisor and its managed workers
    pub fn get_status(&self) -> Result<SupervisorStatus> {
        let leases = self.store.list_worker_leases()?;
        let active_leases = leases.iter().filter(|l| l.task_id.is_some()).count();
        let idle_leases = leases.len() - active_leases;

        let queued = self.store.list_queued_tasks(None, 50)?;
        let queued_count = queued
            .iter()
            .filter(|t| t.status == "queued" || t.status == "retrying")
            .count();

        let running_tasks = queued.iter().filter(|t| t.status == "running").count();
        let gov_decision = GovernanceEngine::evaluate_dispatch(
            self.store.as_ref(),
            &self.config.governance,
            running_tasks,
            None,
            None,
        )?;

        let wip_reallocation_active =
            !gov_decision.allowed && gov_decision.reason.contains("WIP limit reached");

        Ok(SupervisorStatus {
            pid: Some(std::process::id()),
            running: true,
            max_concurrency: self.config.supervisor.max_concurrent_agents,
            active_leases,
            idle_leases,
            queued_tasks_count: queued_count,
            wip_reallocation_active,
            slo_defense_active: gov_decision.defense_mode_active,
            leases,
            queued_tasks: queued,
        })
    }

    /// Main supervisor loop
    pub fn run_loop(&self, running: Arc<AtomicBool>) -> Result<()> {
        while running.load(Ordering::SeqCst) {
            let _ = self.tick();
            std::thread::sleep(Duration::from_millis(500));
        }
        Ok(())
    }

    /// Handle IPC command
    #[cfg(unix)]
    pub fn handle_ipc_command(&self, cmd: &str) -> String {
        let trimmed = cmd.trim();
        let parts: Vec<&str> = trimmed.split_whitespace().collect();
        let action = parts.first().copied().unwrap_or("");

        match action {
            "status" => match self.get_status() {
                Ok(status) => serde_json::to_string_pretty(&status).unwrap_or_default(),
                Err(e) => format!("{{\"error\": \"{}\"}}", e),
            },
            "stop" => "{\"status\": \"stopping\"}".to_string(),
            "pause" => {
                if let Some(task_id) = parts.get(1) {
                    match self.store.update_queued_task_status(
                        task_id,
                        "awaiting_human",
                        Some("Manual pause via CLI"),
                    ) {
                        Ok(_) => {
                            format!("{{\"status\": \"paused\", \"task_id\": \"{}\"}}", task_id)
                        }
                        Err(e) => format!("{{\"error\": \"{}\"}}", e),
                    }
                } else {
                    "{\"error\": \"Missing task_id\"}".to_string()
                }
            }
            "resume" => {
                if let Some(task_id) = parts.get(1) {
                    match self
                        .store
                        .update_queued_task_status(task_id, "queued", None)
                    {
                        Ok(_) => {
                            format!("{{\"status\": \"resumed\", \"task_id\": \"{}\"}}", task_id)
                        }
                        Err(e) => format!("{{\"error\": \"{}\"}}", e),
                    }
                } else {
                    "{\"error\": \"Missing task_id\"}".to_string()
                }
            }
            "cancel" => {
                if let Some(task_id) = parts.get(1) {
                    match self.store.update_queued_task_status(
                        task_id,
                        "cancelled",
                        Some("Cancelled via CLI"),
                    ) {
                        Ok(_) => format!(
                            "{{\"status\": \"cancelled\", \"task_id\": \"{}\"}}",
                            task_id
                        ),
                        Err(e) => format!("{{\"error\": \"{}\"}}", e),
                    }
                } else {
                    "{\"error\": \"Missing task_id\"}".to_string()
                }
            }
            _ => format!("{{\"error\": \"Unknown command '{}'\"}}", action),
        }
    }

    /// Run non-blocking Unix socket IPC server
    pub fn run_ipc_server(&self, socket_path: &Path, running: Arc<AtomicBool>) -> Result<()> {
        #[cfg(unix)]
        {
            if let Some(p) = socket_path.parent() {
                let _ = fs::create_dir_all(p);
            }
            if socket_path.exists() {
                let _ = fs::remove_file(socket_path);
            }

            let listener = UnixListener::bind(socket_path)?;
            listener.set_nonblocking(true)?;

            while running.load(Ordering::SeqCst) {
                match listener.accept() {
                    Ok((mut stream, _)) => {
                        let mut reader = BufReader::new(stream.try_clone()?);
                        let mut line = String::new();
                        if reader.read_line(&mut line).is_ok() {
                            let resp = self.handle_ipc_command(&line);
                            let _ = write!(stream, "{}", resp);
                            let _ = stream.flush();

                            if line.trim() == "stop" {
                                running.store(false, Ordering::SeqCst);
                            }
                        }
                    }
                    Err(ref e) if e.kind() == std::io::ErrorKind::WouldBlock => {
                        std::thread::sleep(Duration::from_millis(50));
                    }
                    Err(e) => {
                        eprintln!("[SUPERVISOR IPC ERROR] {}", e);
                        std::thread::sleep(Duration::from_millis(100));
                    }
                }
            }

            let _ = fs::remove_file(socket_path);
        }
        Ok(())
    }
}

pub fn send_supervisor_ipc(socket_path: &Path, command: &str) -> Result<String> {
    #[cfg(unix)]
    {
        let mut stream = UnixStream::connect(socket_path).with_context(|| {
            format!(
                "Failed to connect to supervisor socket at {}",
                socket_path.display()
            )
        })?;
        stream.set_read_timeout(Some(Duration::from_secs(5)))?;
        stream.set_write_timeout(Some(Duration::from_secs(5)))?;
        writeln!(stream, "{}", command)?;
        stream.flush()?;

        let mut reader = BufReader::new(stream);
        let mut response = String::new();
        reader.read_to_string(&mut response)?;
        Ok(response)
    }
    #[cfg(not(unix))]
    {
        anyhow::bail!("Unix socket IPC is only supported on Unix platforms");
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::storage::SqliteAnalyticsStore;
    use tempfile::tempdir;

    #[test]
    fn test_supervisor_scheduler_and_leases() {
        let td = tempdir().unwrap();
        let db_path = td.path().join("factory.db");
        let store = Arc::new(SqliteAnalyticsStore::open_or_create(&db_path).unwrap());

        let mut config = FactoryConfig::default();
        config.supervisor.max_concurrent_agents = 2;
        config.supervisor.slot_uid_start = 2001;
        config.supervisor.slot_proxy_port_start = 8081;

        let sup = HostSupervisor::new(store.clone(), config, td.path().to_path_buf()).unwrap();

        // Enqueue 3 tasks (prio 10, prio 20, prio 30)
        for i in 1..=3 {
            let task = QueuedTask {
                task_id: format!("task-{:03}", i),
                role: "feature".to_string(),
                req_ids: vec!["REQ-1".to_string()],
                kr_ids: vec!["KR-1".to_string()],
                priority: i * 10,
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
            store.enqueue_task(&task).unwrap();
        }

        // Tick 1: claims 2 tasks (concurrency limit = 2)
        let summary1 = sup.tick().unwrap();
        assert_eq!(summary1.claimed_tasks.len(), 2);
        assert_eq!(summary1.claimed_tasks, vec!["task-001", "task-002"]);
        assert_eq!(summary1.active_workers, 2);
        assert_eq!(summary1.idle_slots, 0);

        // Tick 2: no idle slots -> 0 claimed
        let summary2 = sup.tick().unwrap();
        assert_eq!(summary2.claimed_tasks.len(), 0);
        assert_eq!(summary2.active_workers, 2);

        // Finish task-001 -> releases slot 0
        store
            .update_queued_task_status("task-001", "completed", None)
            .unwrap();

        // Tick 3: slot 0 is idle -> claims task-003
        let summary3 = sup.tick().unwrap();
        assert_eq!(summary3.claimed_tasks, vec!["task-003"]);
        assert_eq!(summary3.active_workers, 2);
    }

    #[test]
    fn test_supervisor_wip_reallocation() {
        let td = tempdir().unwrap();
        let db_path = td.path().join("factory.db");
        let store = Arc::new(SqliteAnalyticsStore::open_or_create(&db_path).unwrap());

        let mut config = FactoryConfig::default();
        config.governance.max_wip_prs = 1;
        config.governance.wip_mode = "local_only".to_string();
        config.supervisor.max_concurrent_agents = 2;
        config.supervisor.reallocate_roles = vec!["review_assist".to_string()];

        let sup = HostSupervisor::new(store.clone(), config, td.path().to_path_buf()).unwrap();

        // Task 1: running feature (reaches max_wip_prs = 1)
        let t1 = QueuedTask {
            task_id: "running-feat".to_string(),
            role: "feature".to_string(),
            req_ids: vec![],
            kr_ids: vec![],
            priority: 1,
            status: "running".to_string(),
            attempt_count: 0,
            model_tier: "local".to_string(),
            assigned_uid: Some(2001),
            proxy_port: Some(8081),
            lease_expires_at: Some(9999999999),
            failure_context: None,
            created_at: "1000".to_string(),
            updated_at: "1000".to_string(),
        };
        store.enqueue_task(&t1).unwrap();

        // Enqueue 1 feature task (priority 5) and 1 review_assist task (priority 10)
        let feat = QueuedTask {
            task_id: "feat-queued".to_string(),
            role: "feature".to_string(),
            req_ids: vec![],
            kr_ids: vec![],
            priority: 5,
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
        let rev = QueuedTask {
            task_id: "review-queued".to_string(),
            role: "review_assist".to_string(),
            req_ids: vec![],
            kr_ids: vec![],
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
        store.enqueue_task(&feat).unwrap();
        store.enqueue_task(&rev).unwrap();

        // Tick: WIP reached -> skips "feat-queued" even though prio 5 < 10, claims "review-queued"!
        let summary = sup.tick().unwrap();
        assert!(summary.wip_reallocation_active);
        assert_eq!(summary.claimed_tasks, vec!["review-queued"]);
    }

    #[test]
    fn test_supervisor_ipc_commands() {
        let td = tempdir().unwrap();
        let db_path = td.path().join("factory.db");
        let store = Arc::new(SqliteAnalyticsStore::open_or_create(&db_path).unwrap());
        let config = FactoryConfig::default();
        let sup = HostSupervisor::new(store.clone(), config, td.path().to_path_buf()).unwrap();

        let t = QueuedTask {
            task_id: "test-task".to_string(),
            role: "feature".to_string(),
            req_ids: vec![],
            kr_ids: vec![],
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
        store.enqueue_task(&t).unwrap();

        // Status command
        let status_json = sup.handle_ipc_command("status");
        assert!(status_json.contains("\"running\": true"));
        assert!(status_json.contains("test-task"));

        // Pause command
        let pause_resp = sup.handle_ipc_command("pause test-task");
        assert!(pause_resp.contains("\"status\": \"paused\""));
        assert_eq!(
            store.get_queued_task("test-task").unwrap().unwrap().status,
            "awaiting_human"
        );

        // Resume command
        let resume_resp = sup.handle_ipc_command("resume test-task");
        assert!(resume_resp.contains("\"status\": \"resumed\""));
        assert_eq!(
            store.get_queued_task("test-task").unwrap().unwrap().status,
            "queued"
        );

        // Cancel command
        let cancel_resp = sup.handle_ipc_command("cancel test-task");
        assert!(cancel_resp.contains("\"status\": \"cancelled\""));
        assert_eq!(
            store.get_queued_task("test-task").unwrap().unwrap().status,
            "cancelled"
        );
    }

    #[test]
    fn test_supervisor_diagnostician_deduplication() {
        let td = tempdir().unwrap();
        let store =
            Arc::new(SqliteAnalyticsStore::open_or_create(&td.path().join("factory.db")).unwrap());
        let mut config = FactoryConfig::default();
        config.supervisor.max_concurrent_agents = 2;
        config.governance.self_optimization.enabled = true;
        config.governance.self_optimization.min_failure_class_count = 2;
        config.governance.self_optimization.cooldown_hours = 24;
        config
            .governance
            .self_optimization
            .auto_enqueue_diagnostician = true;

        // Seed 2 prod_signals for db_deadlock
        for i in 1..=2 {
            let sig = crate::storage::ProdSignalRecord {
                signal_id: format!("sig-deadlock-{}", i),
                task_id: Some(format!("task-{}", i)),
                deploy_sha: "beef".to_string(),
                environment: "prod".to_string(),
                observed_at: "2026-11-24T10:00:00Z".to_string(),
                error_rate_delta: 0.05,
                p95_latency_delta_ms: 100.0,
                slo_budget_burn_pct: 0.1,
                incident_triggered: true,
                mttr_sec: Some(120.0),
                failure_class: Some("db_deadlock".to_string()),
            };
            store.insert_prod_signal(&sig).unwrap();
        }

        let sup = HostSupervisor::new(store.clone(), config, td.path().to_path_buf()).unwrap();

        // Tick 1: Should detect recurring db_deadlock and enqueue 1 diagnostician task
        let summary1 = sup.tick().unwrap();
        assert_eq!(summary1.enqueued_diagnostic_tasks.len(), 1);
        let task_id = &summary1.enqueued_diagnostic_tasks[0];
        let enqueued_task = store.get_queued_task(task_id).unwrap().unwrap();
        assert_eq!(enqueued_task.role, "factory_diagnostician");
        assert_eq!(enqueued_task.priority, 90);
        assert!(enqueued_task
            .failure_context
            .as_ref()
            .unwrap()
            .contains("db_deadlock"));

        // Tick 2: Cooldown (24h) prevents duplicate enqueuing of db_deadlock
        let summary2 = sup.tick().unwrap();
        assert_eq!(summary2.enqueued_diagnostic_tasks.len(), 0);
    }
}
