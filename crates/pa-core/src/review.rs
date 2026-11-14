use anyhow::Result;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

use crate::backend::get_backend;
use crate::schema::load_factory_config;

pub fn review_agent_workspace(
    agent_id: &str,
    host_repo: Option<&Path>,
    open_ide: bool,
    ide_cmd: Option<&str>,
    mock: bool,
) -> Result<PathBuf> {
    let cwd = std::env::current_dir()?;
    let repo = host_repo.unwrap_or(&cwd);
    let worktree_path = repo.join(".pa").join("review").join(agent_id);

    if mock {
        fs::create_dir_all(&worktree_path)?;
        return Ok(worktree_path);
    }

    let config = load_factory_config(Some(&repo.join("factory.toml")))?;
    if let Ok(backend) = get_backend(&config) {
        let _ = backend.fetch_agent_branch(agent_id, repo);
    } else {
        if let Some(parent) = worktree_path.parent() {
            fs::create_dir_all(parent)?;
        }
        if !worktree_path.exists() {
            let _ = Command::new("git")
                .args([
                    "worktree",
                    "add",
                    worktree_path.to_str().unwrap_or(""),
                    &format!("pa/{}/task", agent_id),
                ])
                .current_dir(repo)
                .output();
        }
    }

    if open_ide {
        let cmd = ide_cmd
            .map(|s| s.to_string())
            .or_else(|| std::env::var("VISUAL").ok())
            .or_else(|| std::env::var("EDITOR").ok())
            .unwrap_or_else(|| "code".to_string());

        let _ = Command::new(&cmd)
            .arg(worktree_path.to_str().unwrap_or(""))
            .spawn();
    }

    Ok(worktree_path)
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn test_review_agent_workspace_mock() {
        let td = tempdir().unwrap();
        let wt = review_agent_workspace("agent1", Some(td.path()), false, None, true).unwrap();
        assert!(wt.exists());
        assert_eq!(wt, td.path().join(".pa").join("review").join("agent1"));
    }
}
