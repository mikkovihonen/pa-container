use anyhow::Result;
use std::path::{Path, PathBuf};

use crate::schema::{AgentSpec, FactoryConfig};

pub trait FactoryBackend: Send + Sync {
    fn start_proxy(&self, config: &FactoryConfig) -> Result<String>;
    fn ensure_factory_vm(&self, config: &FactoryConfig, proxy_ip: &str) -> Result<()>;
    fn sync_git_to_vault(&self, host_repo: &Path, branch: &str) -> Result<String>;
    fn launch_agent(&self, agent: &AgentSpec, task_prompt: Option<&str>) -> Result<i32>;
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
