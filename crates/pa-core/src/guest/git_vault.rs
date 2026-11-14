use anyhow::{Context, Result};
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

pub const DEFAULT_VAULT_ROOT: &str = "/var/pa-vault";

pub const PRE_RECEIVE_HOOK: &str = r#"#!/usr/bin/env python3
import sys
import os

agent_id = os.environ.get("PA_AGENT_ID", "")
user = os.environ.get("USER", "")
allowed_prefix = os.environ.get("PA_BRANCH_PREFIX", f"pa/{agent_id}")

for line in sys.stdin:
    oldrev, newrev, refname = line.strip().split()
    if refname.startswith("refs/heads/"):
        branch = refname[len("refs/heads/"):]
        if allowed_prefix and not branch.startswith(allowed_prefix):
            sys.stderr.write(
                f"PA-Git-Vault: Access Denied. Agent '{agent_id}' (user '{user}') "
                f"can only push to '{allowed_prefix}/*', but attempted push to '{branch}'.\n"
            )
            sys.exit(1)
sys.exit(0)
"#;

pub struct GitVaultManager {
    vault_root: PathBuf,
}

impl GitVaultManager {
    pub fn new(vault_root: Option<PathBuf>) -> Self {
        Self {
            vault_root: vault_root.unwrap_or_else(|| PathBuf::from(DEFAULT_VAULT_ROOT)),
        }
    }

    pub fn get_repo_path(&self, project_name: &str) -> PathBuf {
        self.vault_root.join(format!("{}.git", project_name))
    }

    pub fn get_reference_checkout(&self, project_name: &str) -> PathBuf {
        self.vault_root
            .join("checkouts")
            .join(format!("{}-main", project_name))
    }

    pub fn init_bare_vault(&self, project_name: &str) -> Result<PathBuf> {
        let repo_path = self.get_repo_path(project_name);
        fs::create_dir_all(&repo_path)?;

        if !repo_path.join("HEAD").is_file() {
            let status = Command::new("git")
                .args(["init", "--bare", repo_path.to_str().unwrap_or("")])
                .status()
                .context("Failed to run git init --bare")?;
            if !status.success() {
                anyhow::bail!("git init --bare exited with failure");
            }
        }

        let hooks_dir = repo_path.join("hooks");
        fs::create_dir_all(&hooks_dir)?;
        let hook_file = hooks_dir.join("pre-receive");
        fs::write(&hook_file, PRE_RECEIVE_HOOK)?;

        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let _ = fs::set_permissions(&hook_file, fs::Permissions::from_mode(0o755));
        }

        Ok(repo_path)
    }

    pub fn cow_clone_workspace(
        &self,
        project_name: &str,
        destination: &Path,
        agent_id: &str,
        branch_name: Option<&str>,
        mock_cow: bool,
    ) -> Result<PathBuf> {
        let ref_checkout = self.get_reference_checkout(project_name);

        if destination.exists() {
            let _ = fs::remove_dir_all(destination);
        }
        if let Some(parent) = destination.parent() {
            fs::create_dir_all(parent)?;
        }

        if !ref_checkout.exists() {
            let repo_path = self.get_repo_path(project_name);
            let _ = Command::new("git")
                .args([
                    "clone",
                    repo_path.to_str().unwrap_or(""),
                    destination.to_str().unwrap_or(""),
                ])
                .status();
        } else if mock_cow {
            let _ = copy_dir_all(&ref_checkout, destination);
        } else if cfg!(target_os = "macos") {
            let res = Command::new("cp")
                .args([
                    "-c",
                    "-R",
                    ref_checkout.to_str().unwrap_or(""),
                    destination.to_str().unwrap_or(""),
                ])
                .status();
            if res.is_err() || !res.unwrap().success() {
                let _ = copy_dir_all(&ref_checkout, destination);
            }
        } else {
            let res = Command::new("cp")
                .args([
                    "--reflink=always",
                    "-a",
                    ref_checkout.to_str().unwrap_or(""),
                    destination.to_str().unwrap_or(""),
                ])
                .status();
            if res.is_err() || !res.unwrap().success() {
                let _ = copy_dir_all(&ref_checkout, destination);
            }
        }

        let default_branch = format!("pa/{}/task", agent_id);
        let target_branch = branch_name.unwrap_or(&default_branch);
        if destination.join(".git").exists() {
            let _ = Command::new("git")
                .args(["checkout", "-B", target_branch])
                .current_dir(destination)
                .status();
        }

        Ok(destination.to_path_buf())
    }
}

fn copy_dir_all(src: &Path, dst: &Path) -> Result<()> {
    fs::create_dir_all(dst)?;
    for entry in fs::read_dir(src)? {
        let entry = entry?;
        let ty = entry.file_type()?;
        let dest_child = dst.join(entry.file_name());
        if ty.is_dir() {
            copy_dir_all(&entry.path(), &dest_child)?;
        } else {
            fs::copy(entry.path(), dest_child)?;
        }
    }
    Ok(())
}
