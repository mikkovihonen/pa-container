use anyhow::Result;
use std::fs;
use std::path::{Path, PathBuf};

use crate::manifest::ResolvedCapabilities;
use crate::schema::{AgentSpec, FactoryConfig};

pub trait FactoryBackend: Send + Sync {
    fn start_proxy(&self, config: &FactoryConfig) -> Result<String>;
    fn ensure_factory_vm(&self, config: &FactoryConfig, proxy_ip: &str) -> Result<()>;
    fn sync_git_to_vault(&self, host_repo: &Path, branch: &str) -> Result<String>;
    fn provision_packages(&self, packages: &[String]) -> Result<()>;
    fn provision_capabilities(&self, caps: &ResolvedCapabilities) -> Result<()>;
    fn launch_agent(
        &self,
        agent: &AgentSpec,
        task_prompt: Option<&str>,
        capabilities: Option<&ResolvedCapabilities>,
    ) -> Result<i32>;
    fn fetch_agent_branch(&self, agent_id: &str, host_repo: &Path) -> Result<PathBuf>;
    fn stop_factory(&self) -> Result<()>;
    fn get_status(&self) -> Result<serde_json::Value>;
}

pub fn get_backend(config: &FactoryConfig) -> Result<Box<dyn FactoryBackend>> {
    let b_type = config.compute.backend.to_lowercase();
    match b_type.as_str() {
        "auto" => {
            if cfg!(target_os = "macos") {
                Ok(Box::new(
                    crate::backends::tart_macos::TartMacOSBackend::new(
                        Some(config.clone()),
                        None,
                        None,
                        None,
                        None,
                    ),
                ))
            } else {
                Ok(Box::new(
                    crate::backends::incus_linux::IncusLinuxBackend::new(
                        Some(config.clone()),
                        None,
                        None,
                        None,
                        None,
                    ),
                ))
            }
        }
        "macos-tart" | "tart" => Ok(Box::new(
            crate::backends::tart_macos::TartMacOSBackend::new(
                Some(config.clone()),
                None,
                None,
                None,
                None,
            ),
        )),
        "linux-incus" | "incus" => Ok(Box::new(
            crate::backends::incus_linux::IncusLinuxBackend::new(
                Some(config.clone()),
                None,
                None,
                None,
                None,
            ),
        )),
        other => anyhow::bail!("Unsupported compute backend: {}", other),
    }
}

static PROXY_MUTEX: std::sync::Mutex<()> = std::sync::Mutex::new(());

pub fn ensure_proxy_server(
    _proxy_ip: &str,
    config_path: &Path,
    _agents: &[AgentSpec],
) -> Result<()> {
    let _lock = PROXY_MUTEX.lock().unwrap();

    let cache_dir = config_path
        .parent()
        .map(|p| p.to_path_buf())
        .unwrap_or_else(dirs_fallback_cache);
    let sockets_dir = cache_dir.join("sockets");
    fs::create_dir_all(&sockets_dir)?;

    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let _ = fs::set_permissions(&sockets_dir, fs::Permissions::from_mode(0o777));
    }

    #[cfg(unix)]
    {
        use std::os::unix::net::UnixStream;
        let admin_sock = sockets_dir.join("admin.sock");
        if admin_sock.exists() {
            if let Ok(_stream) = UnixStream::connect(&admin_sock) {
                return Ok(());
            }
        }
    }

    if let Ok(_stream) = std::net::TcpStream::connect("127.0.0.1:8080") {
        return Ok(());
    }

    let admin_password = crate::manifest::TokenRuleSpec {
        env_var: "ADMIN_PASSWORD".to_string(),
        keyring_service: Some("pa-container".to_string()),
        keyring_key: Some("ADMIN_PASSWORD".to_string()),
        allowed_hosts: Vec::new(),
    }
    .resolve_secret()
    .map(|s| (*s).clone())
    .unwrap_or_else(|| "pa-factory-session-admin-pass-2026".to_string());

    if let Ok(cwd) = std::env::current_dir() {
        let proxy_dir = cwd.join("coding-agent-proxy");
        if proxy_dir.join("addons").exists() {
            let mut modes = vec!["--mode".to_string(), "regular@127.0.0.1:8080".to_string()];
            if std::net::UdpSocket::bind("127.0.0.1:5353").is_ok() {
                modes.push("--mode".to_string());
                modes.push("dns@5353".to_string());
            }

            let mut uv_cmd = std::process::Command::new("uv");
            uv_cmd.args([
                "run",
                "--group",
                "proxy",
                "mitmweb",
                "--web-host",
                "127.0.0.1",
                "--set",
                &format!("multi_agent_config={}", config_path.display()),
                "--set",
                &format!("web_password={}", admin_password),
                "-s",
                proxy_dir
                    .join("addons/multi_agent_context/multi_agent_context.py")
                    .to_str()
                    .unwrap_or(""),
                "-s",
                proxy_dir
                    .join("addons/allowlist/allowlist.py")
                    .to_str()
                    .unwrap_or(""),
                "-s",
                proxy_dir
                    .join("addons/token_replacer/token_replacer.py")
                    .to_str()
                    .unwrap_or(""),
                "-s",
                proxy_dir
                    .join("addons/flow_export/flow_export.py")
                    .to_str()
                    .unwrap_or(""),
                "-s",
                proxy_dir
                    .join("addons/otlp_exporter/otlp_exporter.py")
                    .to_str()
                    .unwrap_or(""),
            ]);
            uv_cmd.args(&modes);
            uv_cmd.env("PA_SOCKETS_DIR", &sockets_dir);
            uv_cmd.env("FLOW_EXPORT_ENABLED", "true");
            uv_cmd.env("FLOW_EXPORT_DIR", &cache_dir);
            uv_cmd.env("PA_PROXY_BINDINGS", cache_dir.join("proxy-bindings.json"));
            uv_cmd.env(
                "ALLOWLIST_CONFIG_PATH",
                proxy_dir.join("addons/allowlist/allowlist_config.yaml"),
            );
            uv_cmd.env(
                "TOKEN_REPLACER_CONFIG_PATH",
                proxy_dir.join("addons/token_replacer/token_replacer.yaml"),
            );
            uv_cmd.env("PA_MULTI_AGENT_CONFIG", config_path);
            uv_cmd.stdin(std::process::Stdio::null());
            uv_cmd.stdout(std::process::Stdio::null());
            uv_cmd.stderr(std::process::Stdio::null());

            if let Ok(_child) = uv_cmd.spawn() {
                let start = std::time::Instant::now();
                while start.elapsed() < std::time::Duration::from_secs(5) {
                    #[cfg(unix)]
                    {
                        let admin_sock = sockets_dir.join("admin.sock");
                        if admin_sock.exists() {
                            if let Ok(mut stream) =
                                std::os::unix::net::UnixStream::connect(&admin_sock)
                            {
                                use std::io::Write;
                                let _ =
                                    stream.write_all(b"GET / HTTP/1.1\r\nHost: localhost\r\n\r\n");
                                return Ok(());
                            }
                        }
                    }
                    std::thread::sleep(std::time::Duration::from_millis(200));
                }
                return Ok(());
            }
        }
    }

    Ok(())
}

pub fn stop_proxy_server() -> Result<()> {
    let _ = std::process::Command::new("podman")
        .args(["stop", "-t", "1", "pa-proxy"])
        .status();
    let _ = std::process::Command::new("pkill")
        .args(["-f", "mitmweb.*multi_agent_config"])
        .status();
    Ok(())
}

pub fn dirs_fallback_cache() -> PathBuf {
    if let Ok(home) = std::env::var("HOME") {
        PathBuf::from(home).join(".cache").join("pa-container")
    } else {
        std::env::temp_dir().join("pa-container")
    }
}

pub fn assert_backend_conformance<B: FactoryBackend + ?Sized>(
    backend: &B,
    config: &crate::schema::FactoryConfig,
) {
    let proxy_ip = backend
        .start_proxy(config)
        .expect("Proxy start must succeed");
    assert!(!proxy_ip.is_empty(), "Proxy gateway IP must not be empty");

    let cache_dir = dirs_fallback_cache();
    let proxy_cfg_path = cache_dir.join("multi_agent_proxy.json");
    assert!(
        proxy_cfg_path.exists(),
        "Proxy configuration file must be generated"
    );
    let cfg_content = std::fs::read_to_string(&proxy_cfg_path).expect("Read proxy config");
    let json_val: serde_json::Value =
        serde_json::from_str(&cfg_content).expect("Parse proxy config JSON");
    let agents_arr = json_val
        .get("agents")
        .and_then(|a| a.as_array())
        .expect("Proxy config must contain 'agents' array");
    assert_eq!(
        agents_arr.len(),
        config.agents.len(),
        "Agent proxy rules count must match config"
    );

    let nonce = b"test_session_nonce_32_bytes_len";
    let token = crate::manifest::derive_placeholder_token(nonce, "agent1", "API_KEY");
    assert!(token.starts_with("pa-tok-agent1-"));
}
