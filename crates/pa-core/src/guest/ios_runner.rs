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
        _proxy_ip: Option<&str>,
        _proxy_port: Option<u16>,
        mock: bool,
    ) -> Result<String> {
        let sim_name = format!("pa-{}-sim", agent_id);
        let dev_type = device_type.unwrap_or("iPhone 16 Pro");
        let rtime = runtime.unwrap_or("iOS18.0");

        if mock {
            let udid = format!("MOCK-UDID-{}", agent_id.to_uppercase());
            self.simulators
                .lock()
                .unwrap()
                .insert(agent_id.to_string(), udid.clone());
            return Ok(udid);
        }

        let output = Command::new("xcrun")
            .args(["simctl", "create", &sim_name, dev_type, rtime])
            .output();

        let udid = match output {
            Ok(out) if out.status.success() => {
                let u = String::from_utf8_lossy(&out.stdout).trim().to_string();
                if self.cert_path.is_file() {
                    let _ = Command::new("xcrun")
                        .args([
                            "simctl",
                            "keychain",
                            &u,
                            "add-root-cert",
                            self.cert_path.to_str().unwrap_or(""),
                        ])
                        .output();
                }
                let _ = Command::new("xcrun")
                    .args(["simctl", "boot", &u])
                    .output();
                u
            }
            _ => {
                format!("FALLBACK-UDID-{}", agent_id)
            }
        };

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
        mock: bool,
    ) -> Result<()> {
        let udid = {
            let sims = self.simulators.lock().unwrap();
            sims.get(agent_id).cloned()
        };

        let udid = match udid {
            Some(u) => u,
            None => bail!("No active simulator found for agent {}", agent_id),
        };

        if mock {
            return Ok(());
        }

        let install_status = Command::new("xcrun")
            .args(["simctl", "install", &udid, app_bundle_path.to_str().unwrap_or("")])
            .status()
            .context("Failed to install app on iOS simulator")?;
        if !install_status.success() {
            bail!("simctl install failed");
        }

        let launch_status = Command::new("xcrun")
            .args(["simctl", "launch", &udid, bundle_id])
            .status()
            .context("Failed to launch app on iOS simulator")?;
        if !launch_status.success() {
            bail!("simctl launch failed");
        }

        Ok(())
    }

    pub fn capture_screenshot(
        &self,
        agent_id: &str,
        output_path: &Path,
        mock: bool,
    ) -> Result<PathBuf> {
        let udid = {
            let sims = self.simulators.lock().unwrap();
            sims.get(agent_id).cloned()
        };

        let udid = match udid {
            Some(u) => u,
            None => bail!("No active simulator found for agent {}", agent_id),
        };

        if mock {
            if let Some(parent) = output_path.parent() {
                fs::create_dir_all(parent)?;
            }
            fs::write(output_path, b"\x89PNG\r\n\x1a\n")?;
            return Ok(output_path.to_path_buf());
        }

        let status = Command::new("xcrun")
            .args(["simctl", "io", &udid, "screenshot", output_path.to_str().unwrap_or("")])
            .status()
            .context("Failed to capture screenshot from iOS simulator")?;
        if !status.success() {
            bail!("simctl io screenshot failed");
        }

        Ok(output_path.to_path_buf())
    }

    pub fn delete_simulator(&self, agent_id: &str, mock: bool) -> Result<()> {
        let udid = {
            let mut sims = self.simulators.lock().unwrap();
            sims.remove(agent_id)
        };

        if let Some(u) = udid {
            if !mock {
                let _ = Command::new("xcrun").args(["simctl", "shutdown", &u]).output();
                let _ = Command::new("xcrun").args(["simctl", "delete", &u]).output();
            }
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn test_ios_runner_mock() {
        let runner = IOSRunnerDaemon::default();
        let udid = runner
            .create_and_boot_simulator("agent1", None, None, None, None, true)
            .unwrap();
        assert_eq!(udid, "MOCK-UDID-AGENT1");

        let td = tempdir().unwrap();
        let img = td.path().join("shot.png");
        let res = runner.capture_screenshot("agent1", &img, true).unwrap();
        assert!(res.is_file());

        runner.delete_simulator("agent1", true).unwrap();
    }
}
