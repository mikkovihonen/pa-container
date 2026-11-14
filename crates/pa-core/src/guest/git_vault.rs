use anyhow::{Context, Result};
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

pub const DEFAULT_VAULT_ROOT: &str = "/var/pa-vault";

pub const PRE_RECEIVE_HOOK: &str = r#"#!/bin/sh
set -eu

AGENT_ID="${PA_AGENT_ID:-}"
if [ -z "$AGENT_ID" ]; then
    AGENT_ID="$(whoami)"
fi
ALLOWED_PREFIX="${PA_BRANCH_PREFIX:-pa/${AGENT_ID}/}"

while read -r oldrev newrev refname; do
    case "$refname" in
        refs/heads/*)
            branch="${refname#refs/heads/}"
            case "$branch" in
                pa/"$AGENT_ID"/*)
                    ;;
                *)
                    echo "PA-Git-Vault: Access Denied. Agent '$AGENT_ID' can only push to '$ALLOWED_PREFIX*', but attempted push to '$branch'." >&2
                    exit 1
                    ;;
            esac
            ;;
    esac
done
exit 0
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
        _mock_cow: bool,
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
            let status = Command::new("git")
                .args([
                    "clone",
                    repo_path.to_str().unwrap_or(""),
                    destination.to_str().unwrap_or(""),
                ])
                .status()
                .context("Failed to clone repository")?;
            if !status.success() {
                anyhow::bail!("git clone failed from {}", repo_path.display());
            }
        } else if cfg!(target_os = "macos") {
            let res = Command::new("cp")
                .args([
                    "-c",
                    "-R",
                    ref_checkout.to_str().unwrap_or(""),
                    destination.to_str().unwrap_or(""),
                ])
                .status()
                .context("Failed to execute APFS clone command")?;
            if !res.success() {
                anyhow::bail!("APFS CoW clone failed on macOS for {}", destination.display());
            }
        } else {
            let res = Command::new("cp")
                .args([
                    "--reflink=always",
                    "-a",
                    ref_checkout.to_str().unwrap_or(""),
                    destination.to_str().unwrap_or(""),
                ])
                .status()
                .context("Failed to execute reflink clone command")?;
            if !res.success() {
                anyhow::bail!("Reflink CoW clone failed on Linux for {}", destination.display());
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


