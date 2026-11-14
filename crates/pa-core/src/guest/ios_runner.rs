use anyhow::{bail, Context, Result};
use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::Mutex;

pub struct IOSRunnerDaemon {
    cert_path: PathBuf,
    simulators: Mutex<HashMap<String, String>>,
}

impl Default for IOSRunnerDaemon {
    fn default() -> Self {
        Self::new(None)
    }
}

impl IOSRunnerDaemon {
    pub fn new(cert_path: Option<PathBuf>) -> Self {
        Self {
            cert_path: cert_path
                .unwrap_or_else(|| PathBuf::from("/opt/pa/certs/mitmproxy-ca-cert.pem")),
            simulators: Mutex::new(HashMap::new()),
        }
    }

    pub fn create_and_boot_simulator(
        &self,
        agent_id: &str,
        device_type: Option<&str>,
        runtime: Option<&str>,
        proxy_ip: Option<&str>,
        proxy_port: Option<u16>,
    ) -> Result<String> {
        let sim_name = format!("pa-{}-sim", agent_id);
        let dev_type = device_type.unwrap_or("iPhone 16 Pro");
        let rtime = runtime.unwrap_or("iOS18.0");

        let output = Command::new("xcrun")
            .args(["simctl", "create", &sim_name, dev_type, rtime])
            .output()
            .with_context(|| format!("Failed to execute xcrun simctl create for '{}'", sim_name))?;

        if !output.status.success() {
            bail!(
                "simctl create failed: {}",
                String::from_utf8_lossy(&output.stderr)
            );
        }

        let udid = String::from_utf8_lossy(&output.stdout).trim().to_string();
        if udid.is_empty() {
            bail!("simctl create returned empty UDID");
        }

        if self.cert_path.is_file() {
            let cert_status = Command::new("xcrun")
                .args([
                    "simctl",
                    "keychain",
                    &udid,
                    "add-root-cert",
                    self.cert_path.to_str().unwrap_or(""),
                ])
                .status()
                .context("Failed to add mitmproxy root cert to simulator keychain")?;
            if !cert_status.success() {
                bail!("simctl keychain add-root-cert failed for UDID {}", udid);
            }
        }

        let boot_status = Command::new("xcrun")
            .args(["simctl", "boot", &udid])
            .status()
            .with_context(|| format!("Failed to boot simulator {}", udid))?;
        if !boot_status.success() {
            bail!("simctl boot failed for UDID {}", udid);
        }

        // Configure simulator global proxy if IP and port are provided
        if let (Some(ip), Some(port)) = (proxy_ip, proxy_port) {
            let proxy_url = format!("http://{}:{}", ip, port);
            let _ = Command::new("xcrun")
                .args([
                    "simctl",
                    "spawn",
                    &udid,
                    "defaults",
                    "write",
                    "com.apple.CFNetwork",
                    "HTTPProxy",
                    ip,
                ])
                .status();
            let _ = Command::new("xcrun")
                .args([
                    "simctl",
                    "spawn",
                    &udid,
                    "defaults",
                    "write",
                    "com.apple.CFNetwork",
                    "HTTPPort",
                    &port.to_string(),
                ])
                .status();
            let _ = Command::new("xcrun")
                .args([
                    "simctl",
                    "spawn",
                    &udid,
                    "defaults",
                    "write",
                    "com.apple.CFNetwork",
                    "HTTPSProxy",
                    ip,
                ])
                .status();
            let _ = Command::new("xcrun")
                .args([
                    "simctl",
                    "spawn",
                    &udid,
                    "defaults",
                    "write",
                    "com.apple.CFNetwork",
                    "HTTPSPort",
                    &port.to_string(),
                ])
                .status();
            let _ = proxy_url;
        }

        self.simulators
            .lock()
            .unwrap()
            .insert(agent_id.to_string(), udid.clone());
        Ok(udid)
    }

    pub fn install_and_launch_app(
        &self,
        agent_id: &str,
        app_bundle_path: &Path,
        bundle_id: &str,
        proxy_ip: Option<&str>,
        proxy_port: Option<u16>,
    ) -> Result<()> {
        let udid = {
            let sims = self.simulators.lock().unwrap();
            sims.get(agent_id).cloned()
        };

        let udid = match udid {
            Some(u) => u,
            None => bail!("No active simulator found for agent {}", agent_id),
        };

        let install_status = Command::new("xcrun")
            .args([
                "simctl",
                "install",
                &udid,
                app_bundle_path.to_str().unwrap_or(""),
            ])
            .status()
            .context("Failed to install app on iOS simulator")?;
        if !install_status.success() {
            bail!("simctl install failed for {}", app_bundle_path.display());
        }

        let mut cmd = Command::new("xcrun");
        if let (Some(ip), Some(port)) = (proxy_ip, proxy_port) {
            let proxy_url = format!("http://{}:{}", ip, port);
            cmd.env("SIMCTL_CHILD_HTTP_PROXY", &proxy_url)
                .env("SIMCTL_CHILD_HTTPS_PROXY", &proxy_url)
                .env("SIMCTL_CHILD_ALL_PROXY", &proxy_url);
        }
        cmd.args(["simctl", "launch", &udid, bundle_id]);

        let launch_status = cmd
            .status()
            .context("Failed to launch app on iOS simulator")?;
        if !launch_status.success() {
            bail!("simctl launch failed for bundle ID {}", bundle_id);
        }

        Ok(())
    }

    pub fn capture_screenshot(&self, agent_id: &str, output_path: &Path) -> Result<PathBuf> {
        let udid = {
            let sims = self.simulators.lock().unwrap();
            sims.get(agent_id).cloned()
        };

        let udid = match udid {
            Some(u) => u,
            None => bail!("No active simulator found for agent {}", agent_id),
        };

        if let Some(parent) = output_path.parent() {
            fs::create_dir_all(parent)?;
        }

        let status = Command::new("xcrun")
            .args([
                "simctl",
                "io",
                &udid,
                "screenshot",
                output_path.to_str().unwrap_or(""),
            ])
            .status()
            .context("Failed to capture screenshot from iOS simulator")?;
        if !status.success() {
            bail!("simctl io screenshot failed for UDID {}", udid);
        }

        Ok(output_path.to_path_buf())
    }

    pub fn delete_simulator(&self, agent_id: &str) -> Result<()> {
        let udid = {
            let mut sims = self.simulators.lock().unwrap();
            sims.remove(agent_id)
        };

        if let Some(u) = udid {
            let _ = Command::new("xcrun")
                .args(["simctl", "shutdown", &u])
                .output();
            let status = Command::new("xcrun")
                .args(["simctl", "delete", &u])
                .status()
                .context("Failed to delete simulator")?;
            if !status.success() {
                bail!("simctl delete failed for UDID {}", u);
            }
        }
        Ok(())
    }
}
