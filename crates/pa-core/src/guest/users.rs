use anyhow::Result;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

pub fn default_home_base() -> PathBuf {
    if cfg!(target_os = "macos") {
        PathBuf::from("/Users")
    } else {
        PathBuf::from("/home")
    }
}

pub fn ensure_agent_user(
    username: &str,
    uid: u32,
    home_base: Option<&Path>,
    mock: bool,
) -> Result<PathBuf> {
    let base = match home_base {
        Some(p) => p.to_path_buf(),
        None => default_home_base(),
    };
    let home = base.join(username);

    if !mock {
        if cfg!(target_os = "macos") {
            let id_check = Command::new("id").arg(username).output();
            if id_check.is_err() || !id_check.unwrap().status.success() {
                let _ = Command::new("sysadminctl")
                    .args([
                        "-addUser",
                        username,
                        "-UID",
                        &uid.to_string(),
                        "-home",
                        home.to_str().unwrap_or(""),
                        "-shell",
                        "/bin/bash",
                    ])
                    .output();
            }
        } else {
            let id_check = Command::new("id").arg(username).output();
            if id_check.is_err() || !id_check.unwrap().status.success() {
                let _ = Command::new("useradd")
                    .args([
                        "-u",
                        &uid.to_string(),
                        "-d",
                        home.to_str().unwrap_or(""),
                        "-m",
                        "-s",
                        "/bin/bash",
                        username,
                    ])
                    .output();
            }
        }
    }

    fs::create_dir_all(&home)?;
    fs::create_dir_all(home.join("workspace"))?;
    fs::create_dir_all(home.join(".cache"))?;
    fs::create_dir_all(home.join(".config"))?;

    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let _ = fs::set_permissions(&home, fs::Permissions::from_mode(0o700));
    }

    Ok(home)
}
