use anyhow::Result;
use sha2::{Digest, Sha256};
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

use crate::bom::models::ToolchainComponent;

pub fn collect_host_toolchain() -> Result<Vec<ToolchainComponent>> {
    let mut tools = Vec::new();

    // 1. rustc
    if let Some(tool) = probe_rustc() {
        tools.push(tool);
    }

    // 2. cargo
    if let Some(tool) = probe_command("cargo", "cargo", "compiler", &["-V"]) {
        tools.push(tool);
    }

    // 3. python3
    if let Some(tool) = probe_command("python3", "python3", "interpreter", &["--version"]) {
        tools.push(tool);
    }

    // 4. uv
    if let Some(tool) = probe_command("uv", "uv", "runtime", &["--version"]) {
        tools.push(tool);
    }

    // 5. node
    if let Some(tool) = probe_command("node", "node", "runtime", &["--version"]) {
        tools.push(tool);
    }

    // 6. clang / gcc
    if let Some(tool) = probe_command("clang", "clang", "compiler", &["--version"]) {
        tools.push(tool);
    }

    // 7. xcodebuild (macOS only)
    #[cfg(target_os = "macos")]
    {
        if let Some(tool) = probe_command("xcodebuild", "xcodebuild", "sdk", &["-version"]) {
            tools.push(tool);
        }
    }

    // Sort deterministically
    tools.sort_by(|a, b| a.kind.cmp(&b.kind).then_with(|| a.name.cmp(&b.name)));

    Ok(tools)
}

fn probe_rustc() -> Option<ToolchainComponent> {
    let output = Command::new("rustc").arg("-vV").output().ok()?;
    if !output.status.success() {
        return None;
    }
    let stdout = String::from_utf8_lossy(&output.stdout);
    let mut release = String::new();
    let mut commit = String::new();
    let mut host = String::new();
    let mut llvm = String::new();

    for line in stdout.lines() {
        let line = line.trim();
        if let Some(val) = line.strip_prefix("release: ") {
            release = val.to_string();
        } else if let Some(val) = line.strip_prefix("commit-hash: ") {
            commit = val.to_string();
        } else if let Some(val) = line.strip_prefix("host: ") {
            host = val.to_string();
        } else if let Some(val) = line.strip_prefix("LLVM version: ") {
            llvm = val.to_string();
        }
    }

    let bin_path = which_path("rustc");
    let sha256 = bin_path.as_deref().and_then(hash_file);

    let commit_or_build = if !commit.is_empty() {
        Some(format!("commit:{}, host:{}, llvm:{}", commit, host, llvm))
    } else {
        None
    };

    Some(ToolchainComponent {
        name: "rustc".to_string(),
        version: release,
        commit_or_build,
        path: bin_path.map(|p| p.to_string_lossy().to_string()),
        binary_sha256: sha256,
        kind: "compiler".to_string(),
    })
}

fn probe_command(name: &str, bin: &str, kind: &str, args: &[&str]) -> Option<ToolchainComponent> {
    let output = Command::new(bin).args(args).output().ok()?;
    if !output.status.success() {
        return None;
    }
    let stdout = String::from_utf8_lossy(&output.stdout);
    let first_line = stdout.lines().next().unwrap_or("").trim().to_string();
    let version = first_line
        .strip_prefix(name)
        .or_else(|| first_line.strip_prefix(bin))
        .unwrap_or(&first_line)
        .trim()
        .to_string();

    let bin_path = which_path(bin);
    let sha256 = bin_path.as_deref().and_then(hash_file);

    Some(ToolchainComponent {
        name: name.to_string(),
        version,
        commit_or_build: None,
        path: bin_path.map(|p| p.to_string_lossy().to_string()),
        binary_sha256: sha256,
        kind: kind.to_string(),
    })
}

pub fn which_path(bin: &str) -> Option<PathBuf> {
    let output = Command::new("which").arg(bin).output().ok()?;
    if output.status.success() {
        let path_str = String::from_utf8_lossy(&output.stdout).trim().to_string();
        if !path_str.is_empty() {
            return Some(PathBuf::from(path_str));
        }
    }
    None
}

pub fn hash_file(path: &Path) -> Option<String> {
    if !path.is_file() {
        return None;
    }
    let bytes = fs::read(path).ok()?;
    let mut hasher = Sha256::new();
    hasher.update(&bytes);
    Some(hex::encode(hasher.finalize()))
}
