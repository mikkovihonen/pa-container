use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::Instant;

use crate::design::TokenCatalog;
use crate::schema::DesignSystemConfig;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct TokenCompileReport {
    pub tool: String,
    pub status: String, // "success", "skipped", "failed"
    pub generated_files: Vec<PathBuf>,
    pub digest: String,
    pub duration_ms: u64,
    pub message: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct TokenFreshnessReport {
    pub is_fresh: bool,
    pub tool: String,
    pub tokens_digest: String,
    pub missing_files: Vec<PathBuf>,
    pub stale_files: Vec<PathBuf>,
    pub tool_available: bool,
    pub warning: Option<String>,
    pub error: Option<String>,
}

pub fn check_tool_availability(tool: &str) -> bool {
    match tool {
        "none" => true,
        "style_dictionary" => {
            Command::new("style-dictionary")
                .arg("--version")
                .output()
                .is_ok()
                || Command::new("npx").arg("--version").output().is_ok()
                || true // built-in DTCG converter is always available
        }
        "terrazzo" => {
            Command::new("tz").arg("--version").output().is_ok()
                || Command::new("npx").arg("--version").output().is_ok()
        }
        "custom_cmd" => true,
        _ => false,
    }
}

pub fn compute_file_digest(path: &Path) -> Result<String> {
    let bytes = fs::read(path).with_context(|| format!("Failed to read {}", path.display()))?;
    let hash = Sha256::digest(&bytes);
    Ok(hex::encode(hash))
}

pub fn check_tokens_freshness(
    root: &Path,
    config: &DesignSystemConfig,
) -> Result<TokenFreshnessReport> {
    let tokens_path = root.join(&config.tokens_path);
    if !tokens_path.exists() {
        return Ok(TokenFreshnessReport {
            is_fresh: false,
            tool: config.compiler.tool.clone(),
            tokens_digest: String::new(),
            missing_files: Vec::new(),
            stale_files: Vec::new(),
            tool_available: check_tool_availability(&config.compiler.tool),
            warning: None,
            error: Some(format!(
                "Tokens file not found at {}",
                tokens_path.display()
            )),
        });
    }

    let tokens_metadata = fs::metadata(&tokens_path)?;
    let tokens_mtime = tokens_metadata
        .modified()
        .unwrap_or(std::time::SystemTime::UNIX_EPOCH);
    let tokens_digest = compute_file_digest(&tokens_path)?;

    let mut missing = Vec::new();
    let mut stale = Vec::new();

    for rel_path in config.compiler.outputs.values() {
        let target_path = root.join(rel_path);
        if !target_path.exists() {
            missing.push(rel_path.clone());
        } else {
            let target_metadata = fs::metadata(&target_path)?;
            let target_mtime = target_metadata
                .modified()
                .unwrap_or(std::time::SystemTime::UNIX_EPOCH);
            if target_mtime < tokens_mtime {
                stale.push(rel_path.clone());
            }
        }
    }

    missing.sort();
    stale.sort();

    let is_fresh = missing.is_empty() && stale.is_empty();
    let tool_available = check_tool_availability(&config.compiler.tool);
    let mut warning = None;
    let mut error = None;

    if !is_fresh {
        if !tool_available {
            if config
                .compiler
                .on_missing_tool
                .eq_ignore_ascii_case("block")
            {
                error = Some(format!(
                    "Token compiler tool '{}' is missing on host (blocked).",
                    config.compiler.tool
                ));
            } else {
                warning = Some(format!(
                    "Compiled design tokens are stale/missing, but compiler tool '{}' is not installed (skipped).",
                    config.compiler.tool
                ));
            }
        } else {
            warning = Some(format!(
                "Compiled design tokens are stale or missing ({} missing, {} stale). Run 'pa design compile' to update.",
                missing.len(),
                stale.len()
            ));
        }
    }

    Ok(TokenFreshnessReport {
        is_fresh,
        tool: config.compiler.tool.clone(),
        tokens_digest,
        missing_files: missing,
        stale_files: stale,
        tool_available,
        warning,
        error,
    })
}

pub fn compile_design_tokens(
    root: &Path,
    config: &DesignSystemConfig,
) -> Result<TokenCompileReport> {
    let start = Instant::now();
    let tokens_path = root.join(&config.tokens_path);
    if !tokens_path.exists() {
        anyhow::bail!("Tokens file not found at {}", tokens_path.display());
    }

    let digest = compute_file_digest(&tokens_path)?;

    if config.compiler.tool == "none" {
        return Ok(TokenCompileReport {
            tool: "none".to_string(),
            status: "skipped".to_string(),
            generated_files: Vec::new(),
            digest,
            duration_ms: start.elapsed().as_millis() as u64,
            message: Some("Token compiler is disabled (tool: none).".to_string()),
        });
    }

    if config.compiler.tool == "custom_cmd" {
        if let Some(ref cmd_args) = config.compiler.custom_cmd {
            if cmd_args.is_empty() {
                anyhow::bail!("custom_cmd argument list is empty in factory.toml");
            }
            let mut cmd = Command::new(&cmd_args[0]);
            cmd.args(&cmd_args[1..]).current_dir(root);
            let out = cmd
                .output()
                .with_context(|| format!("Failed to execute custom_cmd: {:?}", cmd_args))?;
            if !out.status.success() {
                let stderr = String::from_utf8_lossy(&out.stderr);
                anyhow::bail!(
                    "custom_cmd failed with exit code {:?}: {}",
                    out.status.code(),
                    stderr
                );
            }

            let mut generated = Vec::new();
            for rel_path in config.compiler.outputs.values() {
                let p = root.join(rel_path);
                if p.exists() {
                    generated.push(rel_path.clone());
                }
            }
            generated.sort();

            return Ok(TokenCompileReport {
                tool: "custom_cmd".to_string(),
                status: "success".to_string(),
                generated_files: generated,
                digest,
                duration_ms: start.elapsed().as_millis() as u64,
                message: Some(format!("Executed custom command: {:?}", cmd_args)),
            });
        } else {
            anyhow::bail!("tool = 'custom_cmd' requires custom_cmd array in factory.toml");
        }
    }

    // style_dictionary or terrazzo: generate platform outputs
    let catalog = TokenCatalog::from_file(&tokens_path)?;
    let mut generated = Vec::new();

    for (platform, rel_path) in &config.compiler.outputs {
        let out_file = root.join(rel_path);
        if let Some(parent) = out_file.parent() {
            fs::create_dir_all(parent)
                .with_context(|| format!("Failed to create directory {}", parent.display()))?;
        }

        match platform.to_lowercase().as_str() {
            "css" | "web" => {
                let css = format_css_tokens(&catalog);
                fs::write(&out_file, css).with_context(|| {
                    format!("Failed to write CSS tokens to {}", out_file.display())
                })?;
                generated.push(rel_path.clone());
            }
            "swift" | "ios" => {
                let swift = format_swift_tokens(&catalog);
                fs::write(&out_file, swift).with_context(|| {
                    format!("Failed to write Swift tokens to {}", out_file.display())
                })?;
                generated.push(rel_path.clone());
            }
            "kotlin" | "compose" | "android" => {
                let kotlin = format_kotlin_tokens(&catalog);
                fs::write(&out_file, kotlin).with_context(|| {
                    format!("Failed to write Kotlin tokens to {}", out_file.display())
                })?;
                generated.push(rel_path.clone());
            }
            other => {
                let json_content = serde_json::to_string_pretty(&catalog.tokens)?;
                fs::write(&out_file, json_content).with_context(|| {
                    format!(
                        "Failed to write tokens for platform {} to {}",
                        other,
                        out_file.display()
                    )
                })?;
                generated.push(rel_path.clone());
            }
        }
    }

    generated.sort();

    Ok(TokenCompileReport {
        tool: config.compiler.tool.clone(),
        status: "success".to_string(),
        generated_files: generated,
        digest,
        duration_ms: start.elapsed().as_millis() as u64,
        message: Some(format!(
            "Compiled {} tokens across {} platform files",
            catalog.tokens.len(),
            config.compiler.outputs.len()
        )),
    })
}

fn format_css_tokens(catalog: &TokenCatalog) -> String {
    let mut lines = vec![
        "/* Generated by PA-Container 2.0 W3C DTCG Token Compiler */".to_string(),
        ":root {".to_string(),
    ];

    let mut keys: Vec<_> = catalog.tokens.keys().collect();
    keys.sort();

    for k in keys {
        if let Some(tok) = catalog.tokens.get(k) {
            let css_var = format!("--{}", tok.name.replace('.', "-"));
            lines.push(format!("  {}: {};", css_var, tok.value));
        }
    }

    lines.push("}".to_string());
    lines.push(String::new());
    lines.join("\n")
}

fn to_camel_case(name: &str) -> String {
    let parts: Vec<&str> = name
        .split(['.', '-', '_'])
        .filter(|s| !s.is_empty())
        .collect();
    if parts.is_empty() {
        return name.to_string();
    }
    let mut result = parts[0].to_lowercase();
    for p in &parts[1..] {
        let mut chars = p.chars();
        if let Some(first) = chars.next() {
            result.push_str(&first.to_uppercase().collect::<String>());
            result.push_str(&chars.as_str().to_lowercase());
        }
    }
    result
}

fn to_screaming_snake_case(name: &str) -> String {
    let parts: Vec<&str> = name
        .split(['.', '-', '_'])
        .filter(|s| !s.is_empty())
        .collect();
    parts.join("_").to_uppercase()
}

fn format_swift_tokens(catalog: &TokenCatalog) -> String {
    let mut lines = vec![
        "// Generated by PA-Container 2.0 W3C DTCG Token Compiler".to_string(),
        "import Foundation".to_string(),
        String::new(),
        "public enum DesignTokens {".to_string(),
    ];

    let mut keys: Vec<_> = catalog.tokens.keys().collect();
    keys.sort();

    for k in keys {
        if let Some(tok) = catalog.tokens.get(k) {
            let var_name = to_camel_case(&tok.name);
            lines.push(format!(
                "    public static let {}: String = \"{}\"",
                var_name, tok.value
            ));
        }
    }

    lines.push("}".to_string());
    lines.push(String::new());
    lines.join("\n")
}

fn format_kotlin_tokens(catalog: &TokenCatalog) -> String {
    let mut lines = vec![
        "// Generated by PA-Container 2.0 W3C DTCG Token Compiler".to_string(),
        "package com.example.ui".to_string(),
        String::new(),
        "object DesignTokens {".to_string(),
    ];

    let mut keys: Vec<_> = catalog.tokens.keys().collect();
    keys.sort();

    for k in keys {
        if let Some(tok) = catalog.tokens.get(k) {
            let const_name = to_screaming_snake_case(&tok.name);
            lines.push(format!("    const val {} = \"{}\"", const_name, tok.value));
        }
    }

    lines.push("}".to_string());
    lines.push(String::new());
    lines.join("\n")
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    fn fixture_tokens_json() -> &'static str {
        r##"{
  "color": {
    "brand": {
      "primary": {
        "$value": "#2563eb",
        "$type": "color"
      }
    }
  },
  "spacing": {
    "md": {
      "$value": "16px",
      "$type": "dimension"
    }
  }
}"##
    }

    #[test]
    fn test_token_compiler_compile_and_freshness() {
        let dir = tempdir().unwrap();
        let tokens_dir = dir.path().join("design/tokens");
        fs::create_dir_all(&tokens_dir).unwrap();
        let tokens_file = tokens_dir.join("tokens.json");
        fs::write(&tokens_file, fixture_tokens_json()).unwrap();

        let mut config = DesignSystemConfig::default();
        config.compiler.tool = "style_dictionary".to_string();

        // 1. Initial freshness: output files missing -> not fresh
        let fresh_report = check_tokens_freshness(dir.path(), &config).unwrap();
        assert!(!fresh_report.is_fresh);
        assert_eq!(fresh_report.missing_files.len(), 3);

        // 2. Compile tokens -> generates files
        let compile_report = compile_design_tokens(dir.path(), &config).unwrap();
        assert_eq!(compile_report.status, "success");
        assert_eq!(compile_report.generated_files.len(), 3);

        assert!(dir.path().join("src/styles/tokens.css").exists());
        assert!(dir
            .path()
            .join("Sources/DesignSystem/Tokens.swift")
            .exists());
        assert!(dir
            .path()
            .join("app/src/main/java/com/example/ui/Tokens.kt")
            .exists());

        let css = fs::read_to_string(dir.path().join("src/styles/tokens.css")).unwrap();
        assert!(css.contains("--color-brand-primary: #2563eb;"));

        // 3. Now check freshness -> is_fresh must be true
        let fresh_report2 = check_tokens_freshness(dir.path(), &config).unwrap();
        assert!(fresh_report2.is_fresh);
        assert!(fresh_report2.missing_files.is_empty());
        assert!(fresh_report2.stale_files.is_empty());
    }

    #[test]
    fn test_token_compiler_missing_tool_skip_and_block() {
        let dir = tempdir().unwrap();
        let tokens_dir = dir.path().join("design/tokens");
        fs::create_dir_all(&tokens_dir).unwrap();
        let tokens_file = tokens_dir.join("tokens.json");
        fs::write(&tokens_file, fixture_tokens_json()).unwrap();

        let mut config = DesignSystemConfig::default();
        config.compiler.tool = "missing_tool_xyz".to_string();
        config.compiler.on_missing_tool = "skip".to_string();
        config.platforms = vec![];

        // With skip: evaluate_design_gate passes with skipped result
        let report_skip = crate::design::evaluate_design_gate(dir.path(), &config).unwrap();
        assert!(report_skip.is_compliant);
        let comp_res = report_skip.platform_results.get("compiler").unwrap();
        assert_eq!(comp_res.status, "skipped");

        // With block: evaluate_design_gate fails
        config.compiler.on_missing_tool = "block".to_string();
        let report_block = crate::design::evaluate_design_gate(dir.path(), &config).unwrap();
        assert!(!report_block.is_compliant);
        let comp_res_block = report_block.platform_results.get("compiler").unwrap();
        assert_eq!(comp_res_block.status, "failed");
    }
}
