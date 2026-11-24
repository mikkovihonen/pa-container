use anyhow::{bail, Context, Result};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::fs;
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use crate::schema::LlamaServerSpec;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct LlamaServerState {
    pub fingerprint: String,
    pub pid: u32,
    pub host: String,
    pub port: u16,
    pub model_path: Option<String>,
    pub started_at: u64,
    pub log_path: PathBuf,
    pub sessions: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "status", rename_all = "snake_case")]
pub enum LlamaServerStatusInfo {
    Running {
        fingerprint: String,
        pid: u32,
        host: String,
        port: u16,
        model: Option<String>,
        health: HealthState,
        refcount: usize,
        log_path: PathBuf,
    },
    ExternalRunning {
        host: String,
        port: u16,
        health: HealthState,
    },
    Stopped {
        host: String,
        port: u16,
    },
    Disabled,
    MissingBinary {
        searched: String,
    },
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum HealthState {
    Healthy,
    Loading,
    Unhealthy(String),
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum LlamaReleaseResult {
    Disabled,
    NotManaged,
    Retained { remaining_sessions: usize },
    Terminated { pid: u32 },
}

pub fn dirs_fallback_state() -> PathBuf {
    if let Ok(dir) = std::env::var("PA_COMPUTE_STATE_DIR") {
        return PathBuf::from(dir);
    }
    if let Ok(home) = std::env::var("HOME") {
        PathBuf::from(home)
            .join(".local")
            .join("state")
            .join("pa-container")
            .join("compute")
    } else {
        std::env::temp_dir()
            .join("pa-container-state")
            .join("compute")
    }
}

pub fn dirs_fallback_logs() -> PathBuf {
    if let Ok(dir) = std::env::var("PA_COMPUTE_LOG_DIR") {
        return PathBuf::from(dir);
    }
    if let Ok(home) = std::env::var("HOME") {
        PathBuf::from(home)
            .join(".local")
            .join("state")
            .join("pa-container")
            .join("logs")
    } else {
        std::env::temp_dir().join("pa-container-state").join("logs")
    }
}

pub fn dirs_fallback_share() -> PathBuf {
    if let Ok(dir) = std::env::var("PA_COMPUTE_BIN_DIR") {
        return PathBuf::from(dir);
    }
    if let Ok(home) = std::env::var("HOME") {
        PathBuf::from(home)
            .join(".local")
            .join("share")
            .join("pa-container")
            .join("bin")
    } else {
        std::env::temp_dir().join("pa-container-share").join("bin")
    }
}

pub fn compute_config_fingerprint(spec: &LlamaServerSpec) -> String {
    let mut hasher = Sha256::new();
    let model = spec.effective_model_path().unwrap_or("");
    hasher.update(model.as_bytes());
    hasher.update(b"\x00");
    hasher.update(spec.ctx_size.unwrap_or(0).to_le_bytes());
    hasher.update(b"\x00");
    hasher.update(spec.gpu_layers.unwrap_or(-999).to_le_bytes());
    hasher.update(b"\x00");
    hasher.update(spec.port.to_le_bytes());
    hasher.update(b"\x00");
    hasher.update(spec.host.as_bytes());
    hasher.update(b"\x00");
    for arg in &spec.extra_args {
        hasher.update(arg.as_bytes());
        hasher.update(b"\x00");
    }
    let full = hex::encode(hasher.finalize());
    format!("llama-{}", &full[..16])
}

pub struct FileLock {
    file: fs::File,
}

impl FileLock {
    pub fn acquire(path: &Path) -> Result<Self> {
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent)?;
        }
        let file = fs::OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(path)?;

        #[cfg(unix)]
        {
            use std::os::unix::io::AsRawFd;
            let fd = file.as_raw_fd();
            let res = unsafe { libc::flock(fd, libc::LOCK_EX) };
            if res != 0 {
                return Err(std::io::Error::last_os_error().into());
            }
        }

        Ok(Self { file })
    }
}

impl Drop for FileLock {
    fn drop(&mut self) {
        #[cfg(unix)]
        {
            use std::os::unix::io::AsRawFd;
            let fd = self.file.as_raw_fd();
            let _ = unsafe { libc::flock(fd, libc::LOCK_UN) };
        }
    }
}

#[cfg(unix)]
pub fn is_pid_alive(pid: u32) -> bool {
    if pid == 0 {
        return false;
    }
    // If it's a child of ours, reap if it has exited
    let mut status: libc::c_int = 0;
    let wait_res = unsafe { libc::waitpid(pid as libc::pid_t, &mut status, libc::WNOHANG) };
    if wait_res == pid as libc::pid_t {
        return false;
    }

    let res = unsafe { libc::kill(pid as libc::pid_t, 0) };
    if res == 0 {
        true
    } else {
        let err = std::io::Error::last_os_error().raw_os_error();
        err == Some(libc::EPERM)
    }
}

#[cfg(not(unix))]
pub fn is_pid_alive(_pid: u32) -> bool {
    false
}

pub fn resolve_llama_server_binary(spec: &LlamaServerSpec) -> Result<Option<PathBuf>> {
    resolve_llama_server_binary_inner(spec, None)
}

pub fn resolve_llama_server_binary_inner(
    spec: &LlamaServerSpec,
    bin_dir_override: Option<&Path>,
) -> Result<Option<PathBuf>> {
    if let Some(ref bp) = spec.binary_path {
        let p = PathBuf::from(bp);
        if p.is_file() {
            return Ok(Some(p));
        }
        if spec.on_missing_binary.to_lowercase() == "block" {
            bail!(
                "Configured llama-server binary_path '{}' does not exist or is not a file.",
                bp
            );
        } else {
            eprintln!(
                "==> [WARN] llama-server binary_path '{}' not found; searching PATH and default locations.",
                bp
            );
        }
    }

    if let Some(paths) = std::env::var_os("PATH") {
        for path in std::env::split_paths(&paths) {
            let candidate = path.join("llama-server");
            if candidate.is_file() {
                return Ok(Some(candidate));
            }
        }
    }

    let default_bin = bin_dir_override
        .map(|p| p.join("llama-server"))
        .unwrap_or_else(|| dirs_fallback_share().join("llama-server"));
    if default_bin.is_file() {
        return Ok(Some(default_bin));
    }

    if spec.on_missing_binary.to_lowercase() == "block" {
        bail!(
            "llama-server binary not found in PATH or at '{}'. Set compute.llama_server.binary_path or install llama-server.",
            default_bin.display()
        );
    }

    Ok(None)
}

pub fn check_llama_health(host: &str, port: u16) -> HealthState {
    let url = format!("http://{}:{}/health", host, port);
    match ureq::get(&url).timeout(Duration::from_millis(1500)).call() {
        Ok(resp) => {
            if resp.status() == 200 {
                HealthState::Healthy
            } else if resp.status() == 503 {
                HealthState::Loading
            } else {
                HealthState::Unhealthy(format!("HTTP {}", resp.status()))
            }
        }
        Err(ureq::Error::Status(503, _)) => HealthState::Loading,
        Err(ureq::Error::Status(code, _)) => HealthState::Unhealthy(format!("HTTP {}", code)),
        Err(ureq::Error::Transport(e)) => HealthState::Unhealthy(e.to_string()),
    }
}

pub fn read_log_tail(log_path: &Path, max_lines: usize) -> String {
    if !log_path.is_file() {
        return "(Log file does not exist)".to_string();
    }
    match fs::read_to_string(log_path) {
        Ok(content) => {
            let lines: Vec<&str> = content.lines().collect();
            if lines.len() <= max_lines {
                content
            } else {
                lines[lines.len() - max_lines..].join("\n")
            }
        }
        Err(e) => format!("(Failed to read log file: {})", e),
    }
}

pub fn ensure_llama_server(
    spec: &LlamaServerSpec,
    session_id: &str,
) -> Result<LlamaServerStatusInfo> {
    ensure_llama_server_inner(spec, session_id, None, None, None)
}

pub fn ensure_llama_server_inner(
    spec: &LlamaServerSpec,
    session_id: &str,
    state_dir_override: Option<&Path>,
    logs_dir_override: Option<&Path>,
    bin_dir_override: Option<&Path>,
) -> Result<LlamaServerStatusInfo> {
    if !spec.enabled {
        return Ok(LlamaServerStatusInfo::Disabled);
    }

    let state_dir = state_dir_override
        .map(|p| p.to_path_buf())
        .unwrap_or_else(dirs_fallback_state);
    let logs_dir = logs_dir_override
        .map(|p| p.to_path_buf())
        .unwrap_or_else(dirs_fallback_logs);
    fs::create_dir_all(&state_dir)?;
    fs::create_dir_all(&logs_dir)?;

    let fingerprint = compute_config_fingerprint(spec);
    let lock_path = state_dir.join(format!("{}.lock", fingerprint));
    let _lock = FileLock::acquire(&lock_path)?;

    let state_path = state_dir.join(format!("{}.json", fingerprint));
    let log_path = logs_dir.join(format!("{}.log", fingerprint));

    // 1. If managed_lifecycle is false, simply verify external reachability
    if !spec.managed_lifecycle {
        let health = check_llama_health(&spec.host, spec.port);
        match health {
            HealthState::Healthy | HealthState::Loading => {
                return Ok(LlamaServerStatusInfo::ExternalRunning {
                    host: spec.host.clone(),
                    port: spec.port,
                    health,
                });
            }
            HealthState::Unhealthy(_) => {
                return Ok(LlamaServerStatusInfo::Stopped {
                    host: spec.host.clone(),
                    port: spec.port,
                });
            }
        }
    }

    // 2. Check if an active managed state file exists
    if state_path.is_file() {
        if let Ok(content) = fs::read_to_string(&state_path) {
            if let Ok(mut state) = serde_json::from_str::<LlamaServerState>(&content) {
                if is_pid_alive(state.pid) {
                    let health = check_llama_health(&state.host, state.port);
                    if !state.sessions.contains(&session_id.to_string()) {
                        state.sessions.push(session_id.to_string());
                        let _ = fs::write(
                            &state_path,
                            serde_json::to_string_pretty(&state).unwrap_or_default(),
                        );
                    }
                    return Ok(LlamaServerStatusInfo::Running {
                        fingerprint,
                        pid: state.pid,
                        host: state.host,
                        port: state.port,
                        model: state.model_path,
                        health,
                        refcount: state.sessions.len(),
                        log_path: state.log_path,
                    });
                } else {
                    eprintln!(
                        "==> [WARN] Stale llama-server PID {} detected for fingerprint {}. Pruning state file.",
                        state.pid, fingerprint
                    );
                    let _ = fs::remove_file(&state_path);
                }
            }
        }
    }

    // 3. Check if an external instance is already running on this host:port
    let external_health = check_llama_health(&spec.host, spec.port);
    if matches!(external_health, HealthState::Healthy | HealthState::Loading) {
        return Ok(LlamaServerStatusInfo::ExternalRunning {
            host: spec.host.clone(),
            port: spec.port,
            health: external_health,
        });
    }

    // 4. Resolve llama-server binary
    let binary = match resolve_llama_server_binary_inner(spec, bin_dir_override)? {
        Some(b) => b,
        None => {
            return Ok(LlamaServerStatusInfo::MissingBinary {
                searched: spec
                    .binary_path
                    .clone()
                    .unwrap_or_else(|| "PATH & default share".to_string()),
            });
        }
    };

    // 5. Prepare arguments
    let mut args = vec![
        "--host".to_string(),
        spec.host.clone(),
        "--port".to_string(),
        spec.port.to_string(),
    ];

    if let Some(ref m) = spec.effective_model_path() {
        args.push("--model".to_string());
        args.push(m.to_string());
    }

    if let Some(ctx) = spec.ctx_size {
        args.push("--ctx-size".to_string());
        args.push(ctx.to_string());
    }

    if let Some(layers) = spec.gpu_layers {
        args.push("--n-gpu-layers".to_string());
        args.push(layers.to_string());
    }

    for extra in &spec.extra_args {
        args.push(extra.clone());
    }

    // 6. Open log file and spawn child process
    let log_file = fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(&log_path)
        .with_context(|| format!("Failed to open log file at {}", log_path.display()))?;
    let log_file_err = log_file.try_clone()?;

    let mut cmd = std::process::Command::new(&binary);
    cmd.args(&args);
    cmd.stdout(std::process::Stdio::from(log_file));
    cmd.stderr(std::process::Stdio::from(log_file_err));
    cmd.stdin(std::process::Stdio::null());

    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        cmd.process_group(0);
    }

    let child = cmd
        .spawn()
        .with_context(|| format!("Failed to spawn llama-server binary {}", binary.display()))?;

    let child_pid = child.id();
    let started_at = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs();

    // 7. Poll GET /health until HTTP 200 OK or timeout
    let timeout = Duration::from_secs(spec.startup_timeout_sec);
    let start_time = Instant::now();
    let mut is_ready = false;

    while start_time.elapsed() < timeout {
        if !is_pid_alive(child_pid) {
            let tail = read_log_tail(&log_path, 30);
            bail!(
                "llama-server process (PID {}) terminated unexpectedly during startup. Log tail:\n{}",
                child_pid,
                tail
            );
        }

        let health = check_llama_health(&spec.host, spec.port);
        if health == HealthState::Healthy {
            is_ready = true;
            break;
        }

        std::thread::sleep(Duration::from_millis(500));
    }

    if !is_ready {
        #[cfg(unix)]
        unsafe {
            let _ = libc::kill(child_pid as libc::pid_t, libc::SIGTERM);
            std::thread::sleep(Duration::from_millis(500));
            if is_pid_alive(child_pid) {
                let _ = libc::kill(child_pid as libc::pid_t, libc::SIGKILL);
            }
        }
        let tail = read_log_tail(&log_path, 30);
        bail!(
            "llama-server startup timed out after {}s waiting for 200 OK on http://{}:{}/health. Log tail:\n{}",
            spec.startup_timeout_sec,
            spec.host,
            spec.port,
            tail
        );
    }

    // 8. Record state file
    let state = LlamaServerState {
        fingerprint: fingerprint.clone(),
        pid: child_pid,
        host: spec.host.clone(),
        port: spec.port,
        model_path: spec.effective_model_path().map(|s| s.to_string()),
        started_at,
        log_path: log_path.clone(),
        sessions: vec![session_id.to_string()],
    };

    fs::write(
        &state_path,
        serde_json::to_string_pretty(&state).unwrap_or_default(),
    )?;

    Ok(LlamaServerStatusInfo::Running {
        fingerprint,
        pid: child_pid,
        host: spec.host.clone(),
        port: spec.port,
        model: spec.effective_model_path().map(|s| s.to_string()),
        health: HealthState::Healthy,
        refcount: 1,
        log_path,
    })
}

pub fn release_llama_server(
    spec: &LlamaServerSpec,
    session_id: &str,
    force: bool,
) -> Result<LlamaReleaseResult> {
    release_llama_server_inner(spec, session_id, force, None)
}

pub fn release_llama_server_inner(
    spec: &LlamaServerSpec,
    session_id: &str,
    force: bool,
    state_dir_override: Option<&Path>,
) -> Result<LlamaReleaseResult> {
    if !spec.enabled {
        return Ok(LlamaReleaseResult::Disabled);
    }

    let state_dir = state_dir_override
        .map(|p| p.to_path_buf())
        .unwrap_or_else(dirs_fallback_state);
    if !state_dir.is_dir() {
        return Ok(LlamaReleaseResult::NotManaged);
    }

    let fingerprint = compute_config_fingerprint(spec);
    let lock_path = state_dir.join(format!("{}.lock", fingerprint));
    let _lock = FileLock::acquire(&lock_path)?;

    let state_path = state_dir.join(format!("{}.json", fingerprint));
    if !state_path.is_file() {
        return Ok(LlamaReleaseResult::NotManaged);
    }

    let content = fs::read_to_string(&state_path)?;
    let mut state: LlamaServerState = serde_json::from_str(&content)?;

    state.sessions.retain(|s| s != session_id);

    if state.sessions.is_empty() || force {
        let pid = state.pid;
        if is_pid_alive(pid) {
            #[cfg(unix)]
            unsafe {
                let _ = libc::kill(pid as libc::pid_t, libc::SIGTERM);
            }

            let start_term = Instant::now();
            let mut terminated = false;
            while start_term.elapsed() < Duration::from_secs(5) {
                #[cfg(unix)]
                unsafe {
                    let mut status: libc::c_int = 0;
                    let _ = libc::waitpid(pid as libc::pid_t, &mut status, libc::WNOHANG);
                }
                if !is_pid_alive(pid) {
                    terminated = true;
                    break;
                }
                std::thread::sleep(Duration::from_millis(100));
            }

            if !terminated && is_pid_alive(pid) {
                #[cfg(unix)]
                unsafe {
                    let _ = libc::kill(pid as libc::pid_t, libc::SIGKILL);
                    let mut status: libc::c_int = 0;
                    let _ = libc::waitpid(pid as libc::pid_t, &mut status, libc::WNOHANG);
                }
            }
        }

        let _ = fs::remove_file(&state_path);
        Ok(LlamaReleaseResult::Terminated { pid })
    } else {
        fs::write(
            &state_path,
            serde_json::to_string_pretty(&state).unwrap_or_default(),
        )?;
        Ok(LlamaReleaseResult::Retained {
            remaining_sessions: state.sessions.len(),
        })
    }
}

pub fn get_llama_server_status(spec: &LlamaServerSpec) -> Result<LlamaServerStatusInfo> {
    get_llama_server_status_inner(spec, None)
}

pub fn get_llama_server_status_inner(
    spec: &LlamaServerSpec,
    state_dir_override: Option<&Path>,
) -> Result<LlamaServerStatusInfo> {
    if !spec.enabled {
        return Ok(LlamaServerStatusInfo::Disabled);
    }

    let state_dir = state_dir_override
        .map(|p| p.to_path_buf())
        .unwrap_or_else(dirs_fallback_state);
    let fingerprint = compute_config_fingerprint(spec);
    let state_path = state_dir.join(format!("{}.json", fingerprint));

    if state_path.is_file() {
        if let Ok(content) = fs::read_to_string(&state_path) {
            if let Ok(state) = serde_json::from_str::<LlamaServerState>(&content) {
                if is_pid_alive(state.pid) {
                    let health = check_llama_health(&state.host, state.port);
                    return Ok(LlamaServerStatusInfo::Running {
                        fingerprint,
                        pid: state.pid,
                        host: state.host,
                        port: state.port,
                        model: state.model_path,
                        health,
                        refcount: state.sessions.len(),
                        log_path: state.log_path,
                    });
                } else {
                    let _ = fs::remove_file(&state_path);
                }
            }
        }
    }

    let external_health = check_llama_health(&spec.host, spec.port);
    if matches!(external_health, HealthState::Healthy | HealthState::Loading) {
        return Ok(LlamaServerStatusInfo::ExternalRunning {
            host: spec.host.clone(),
            port: spec.port,
            health: external_health,
        });
    }

    Ok(LlamaServerStatusInfo::Stopped {
        host: spec.host.clone(),
        port: spec.port,
    })
}

pub fn inject_compute_endpoints_to_allowlist(config: &mut crate::schema::FactoryConfig) {
    let llama = config.llama_server().clone();
    if llama.enabled {
        let endpoints = vec![
            format!("{}:{}", llama.host, llama.port),
            format!("127.0.0.1:{}", llama.port),
            format!("localhost:{}", llama.port),
        ];
        for agent in &mut config.agents {
            for ep in &endpoints {
                if !agent.allowlist.contains(ep) {
                    agent.allowlist.push(ep.clone());
                }
            }
        }
    }
}

pub fn derive_factory_session_id(
    config: &crate::schema::FactoryConfig,
    config_path: Option<&Path>,
) -> Result<String> {
    let cwd = std::env::current_dir()?;
    let key = if let Some(p) = config_path {
        p.canonicalize().unwrap_or_else(|_| p.to_path_buf())
    } else {
        cwd
    };
    let mut hasher = Sha256::new();
    hasher.update(key.to_string_lossy().as_bytes());
    let hash = hex::encode(hasher.finalize());
    let name = if config.factory.name.is_empty() {
        "factory"
    } else {
        &config.factory.name
    };
    Ok(format!("{}-{}", name, &hash[..8]))
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn test_config_fingerprint_deterministic_and_variant() {
        let spec1 = LlamaServerSpec {
            model_path: Some("/models/modelA.gguf".to_string()),
            port: 8081,
            ctx_size: Some(32768),
            gpu_layers: Some(-1),
            ..Default::default()
        };

        let mut spec2 = spec1.clone();
        assert_eq!(
            compute_config_fingerprint(&spec1),
            compute_config_fingerprint(&spec2)
        );

        // Variant model changes fingerprint
        spec2.model_path = Some("/models/modelB.gguf".to_string());
        assert_ne!(
            compute_config_fingerprint(&spec1),
            compute_config_fingerprint(&spec2)
        );

        // Variant port changes fingerprint
        let mut spec3 = spec1.clone();
        spec3.port = 8089;
        assert_ne!(
            compute_config_fingerprint(&spec1),
            compute_config_fingerprint(&spec3)
        );
    }

    #[test]
    fn test_binary_discovery_skip_vs_block() {
        let dir = tempdir().unwrap();
        let valid_bin = dir.path().join("mock-llama-server");
        fs::write(&valid_bin, b"#!/bin/sh\necho ok\n").unwrap();

        let mut spec = LlamaServerSpec {
            binary_path: Some(valid_bin.to_string_lossy().to_string()),
            on_missing_binary: "block".to_string(),
            ..Default::default()
        };

        let resolved = resolve_llama_server_binary(&spec).unwrap();
        assert_eq!(resolved, Some(valid_bin));

        spec.binary_path = Some("/nonexistent/llama-server-binary-12345".to_string());
        spec.on_missing_binary = "block".to_string();
        let res = resolve_llama_server_binary(&spec);
        assert!(res.is_err());
    }

    #[test]
    fn test_stale_pid_cleanup_in_get_status() {
        let dir = tempdir().unwrap();

        let spec = LlamaServerSpec {
            enabled: true,
            port: 61234, // Unlikely to be used
            ..Default::default()
        };

        let fingerprint = compute_config_fingerprint(&spec);
        let state_path = dir.path().join(format!("{}.json", fingerprint));

        // Write state file with a dead PID (e.g. 9999999)
        let state = LlamaServerState {
            fingerprint: fingerprint.clone(),
            pid: 9999999,
            host: "127.0.0.1".to_string(),
            port: 61234,
            model_path: None,
            started_at: 1000,
            log_path: dir.path().join("llama.log"),
            sessions: vec!["sess-1".to_string()],
        };
        fs::write(&state_path, serde_json::to_string(&state).unwrap()).unwrap();
        assert!(state_path.is_file());

        let status = get_llama_server_status_inner(&spec, Some(dir.path())).unwrap();
        // Stale state file should be removed and status should report Stopped
        assert!(!state_path.is_file());
        assert!(matches!(status, LlamaServerStatusInfo::Stopped { .. }));
    }

    #[test]
    fn test_refcount_session_tracking_and_release() {
        let dir = tempdir().unwrap();

        let spec = LlamaServerSpec {
            enabled: true,
            port: 61235,
            ..Default::default()
        };

        let fingerprint = compute_config_fingerprint(&spec);
        let state_path = dir.path().join(format!("{}.json", fingerprint));

        // Use current process PID so it is alive
        let current_pid = std::process::id();
        let state = LlamaServerState {
            fingerprint: fingerprint.clone(),
            pid: current_pid,
            host: "127.0.0.1".to_string(),
            port: 61235,
            model_path: None,
            started_at: 1000,
            log_path: dir.path().join("llama.log"),
            sessions: vec!["sess-A".to_string(), "sess-B".to_string()],
        };
        fs::write(&state_path, serde_json::to_string(&state).unwrap()).unwrap();

        // Release session A -> should retain session B
        let res1 = release_llama_server_inner(&spec, "sess-A", false, Some(dir.path())).unwrap();
        assert_eq!(
            res1,
            LlamaReleaseResult::Retained {
                remaining_sessions: 1
            }
        );

        let content = fs::read_to_string(&state_path).unwrap();
        let updated: LlamaServerState = serde_json::from_str(&content).unwrap();
        assert_eq!(updated.sessions, vec!["sess-B".to_string()]);

        // Release session B with force = false -> sessions becomes empty, deletes state file
        // Note: we don't want to kill ourselves! So replace state pid with a dummy pid before testing deletion
        let mut state_dummy = updated;
        state_dummy.pid = 9999998; // dead PID
        fs::write(&state_path, serde_json::to_string(&state_dummy).unwrap()).unwrap();

        let res2 = release_llama_server_inner(&spec, "sess-B", false, Some(dir.path())).unwrap();
        assert_eq!(res2, LlamaReleaseResult::Terminated { pid: 9999998 });
        assert!(!state_path.is_file());
    }

    #[test]
    fn test_read_log_tail() {
        let dir = tempdir().unwrap();
        let log_file = dir.path().join("test.log");
        let sample = "line 1\nline 2\nline 3\nline 4\nline 5\n";
        fs::write(&log_file, sample).unwrap();

        let tail = read_log_tail(&log_file, 2);
        assert_eq!(tail, "line 4\nline 5");

        let full = read_log_tail(&log_file, 10);
        assert_eq!(full, sample);
    }

    #[test]
    fn test_ensure_and_release_llama_server_mock() {
        let dir = tempdir().unwrap();
        let state_dir = dir.path().join("state");
        let log_dir = dir.path().join("logs");
        let bin_dir = dir.path().join("bin");
        fs::create_dir_all(&bin_dir).unwrap();

        // Pick a free port
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        drop(listener); // close so child process can bind it

        // Write a mock python HTTP server script that returns 503 twice, then 200
        let mock_py = bin_dir.join("mock_server.py");
        let py_code = r#"
import sys, http.server

CALLS = [0]
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        CALLS[0] += 1
        if CALLS[0] < 3:
            self.send_response(503)
            self.end_headers()
        else:
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
    def log_message(self, format, *args):
        pass

port = int(sys.argv[sys.argv.index('--port') + 1])
http.server.HTTPServer(('127.0.0.1', port), H).serve_forever()
"#;
        fs::write(&mock_py, py_code).unwrap();

        let mock_bin = bin_dir.join("llama-server");
        let sh_code = format!("#!/bin/sh\nexec python3 \"{}\" \"$@\"\n", mock_py.display());
        fs::write(&mock_bin, sh_code).unwrap();
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            fs::set_permissions(&mock_bin, fs::Permissions::from_mode(0o755)).unwrap();
        }

        let spec = LlamaServerSpec {
            enabled: true,
            port,
            host: "127.0.0.1".to_string(),
            binary_path: Some(mock_bin.to_string_lossy().to_string()),
            startup_timeout_sec: 5,
            ..Default::default()
        };

        // 1. First session ensures server starts
        let status1 = ensure_llama_server_inner(
            &spec,
            "sess-1",
            Some(&state_dir),
            Some(&log_dir),
            Some(&bin_dir),
        )
        .unwrap();

        match status1 {
            LlamaServerStatusInfo::Running {
                refcount,
                health,
                pid,
                ..
            } => {
                assert_eq!(refcount, 1);
                assert_eq!(health, HealthState::Healthy);
                assert!(is_pid_alive(pid));

                // 2. Second session connects to the same running instance (refcount becomes 2)
                let status2 = ensure_llama_server_inner(
                    &spec,
                    "sess-2",
                    Some(&state_dir),
                    Some(&log_dir),
                    Some(&bin_dir),
                )
                .unwrap();

                match status2 {
                    LlamaServerStatusInfo::Running {
                        refcount: r2,
                        pid: p2,
                        ..
                    } => {
                        assert_eq!(r2, 2);
                        assert_eq!(p2, pid);
                    }
                    other => panic!("Expected Running status, got {:?}", other),
                }

                // 3. Status inspection matches Running
                let inspected = get_llama_server_status_inner(&spec, Some(&state_dir)).unwrap();
                match inspected {
                    LlamaServerStatusInfo::Running { refcount: r3, .. } => {
                        assert_eq!(r3, 2);
                    }
                    other => panic!("Expected Running status, got {:?}", other),
                }

                // 4. Release session 1 -> refcount drops to 1, process remains alive
                let rel1 =
                    release_llama_server_inner(&spec, "sess-1", false, Some(&state_dir)).unwrap();
                assert_eq!(
                    rel1,
                    LlamaReleaseResult::Retained {
                        remaining_sessions: 1
                    }
                );
                assert!(is_pid_alive(pid));

                // 5. Release session 2 -> refcount drops to 0, process terminates
                let rel2 =
                    release_llama_server_inner(&spec, "sess-2", false, Some(&state_dir)).unwrap();
                assert_eq!(rel2, LlamaReleaseResult::Terminated { pid });
                assert!(!is_pid_alive(pid));
            }
            other => panic!("Expected Running status, got {:?}", other),
        }
    }

    #[test]
    fn test_inject_compute_endpoints_to_allowlist() {
        use crate::schema::FactoryConfig;
        let mut config = FactoryConfig::default();
        config.compute.llama_server.enabled = true;
        config.compute.llama_server.host = "127.0.0.1".to_string();
        config.compute.llama_server.port = 8089;

        assert!(!config.agents[0]
            .allowlist
            .contains(&"127.0.0.1:8089".to_string()));
        inject_compute_endpoints_to_allowlist(&mut config);
        assert!(config.agents[0]
            .allowlist
            .contains(&"127.0.0.1:8089".to_string()));
        assert!(config.agents[0]
            .allowlist
            .contains(&"localhost:8089".to_string()));
    }
}
