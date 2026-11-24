use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet};
use std::fs;
use std::path::Path;
use std::process::Command;

use crate::schema::DesignDriftConfig;

use super::{ComponentContract, DesignLintViolation, TokenCatalog};

#[derive(Debug, Clone, Serialize, Deserialize, Default, PartialEq)]
pub struct DriftScanResult {
    pub violations: Vec<DesignLintViolation>,
    pub raw_primitive_violations: usize,
    pub new_components: Vec<String>,
    pub needs_design_review: bool,
}

pub fn scan_workspace_for_drift(
    root: &Path,
    config: &DesignDriftConfig,
    contracts: &HashMap<String, ComponentContract>,
    catalog: &TokenCatalog,
) -> Result<DriftScanResult> {
    if !config.enabled || config.engine == "none" {
        return Ok(DriftScanResult::default());
    }

    let mut result = DriftScanResult::default();

    // 1. Native AST Tokenizer & Linting
    if config.engine == "native" || config.engine == "hybrid" {
        let contract_paths = collect_contract_component_paths(root, contracts);
        walk_and_scan_drift(
            root,
            root,
            config,
            contracts,
            catalog,
            &contract_paths,
            &mut result,
        )?;
    }

    // 2. External Linter Delegate
    if (config.engine == "external" || config.engine == "hybrid") && config.linter_command.is_some()
    {
        if let Some(ref cmd_str) = config.linter_command {
            let external_violations = run_external_linter(root, cmd_str)?;
            for v in external_violations {
                if v.rule.contains("primitive") || v.rule.contains("raw") {
                    result.raw_primitive_violations += 1;
                }
                result.violations.push(v);
            }
        }
    }

    // Check if new unregistered components should trigger gate failure
    if result.needs_design_review && config.on_new_primitive.eq_ignore_ascii_case("block") {
        for comp in &result.new_components {
            result.violations.push(DesignLintViolation {
                file: "workspace".to_string(),
                line: 1,
                rule: "unregistered_component_blocked".to_string(),
                message: format!(
                    "Unregistered component '{}' blocked gate (on_new_primitive = 'block').",
                    comp
                ),
                severity: "error".to_string(),
            });
        }
    }

    Ok(result)
}

fn collect_contract_component_paths(
    root: &Path,
    contracts: &HashMap<String, ComponentContract>,
) -> HashSet<String> {
    let mut paths = HashSet::new();
    for contract in contracts.values() {
        if let Some(ref w) = contract.web {
            if !w.component.is_empty() {
                paths.insert(normalize_rel_path(root, &root.join(&w.component)));
            }
        }
        if let Some(ref i) = contract.ios {
            if !i.component.is_empty() {
                paths.insert(normalize_rel_path(root, &root.join(&i.component)));
            }
        }
        if let Some(ref a) = contract.android {
            if !a.component.is_empty() {
                paths.insert(normalize_rel_path(root, &root.join(&a.component)));
            }
        }
    }
    paths
}

fn normalize_rel_path(root: &Path, p: &Path) -> String {
    p.strip_prefix(root).unwrap_or(p).display().to_string()
}

fn walk_and_scan_drift(
    base: &Path,
    current: &Path,
    config: &DesignDriftConfig,
    contracts: &HashMap<String, ComponentContract>,
    catalog: &TokenCatalog,
    contract_paths: &HashSet<String>,
    result: &mut DriftScanResult,
) -> Result<()> {
    if !current.is_dir() {
        return Ok(());
    }

    for entry in fs::read_dir(current)?.filter_map(|e| e.ok()) {
        let path = entry.path();
        let name = path.file_name().and_then(|n| n.to_str()).unwrap_or("");

        // Skip standard ignored directories
        if name.starts_with('.')
            || name == "target"
            || name == "node_modules"
            || name == ".venv"
            || name == "__pycache__"
            || name == "site"
            || name == "tokens"
            || name == "design"
            || name == "crates"
        {
            continue;
        }

        let rel = normalize_rel_path(base, &path);

        // Check user ignore patterns
        if matches_ignore(&rel, &config.ignore_paths) {
            continue;
        }

        if path.is_dir() {
            walk_and_scan_drift(
                base,
                &path,
                config,
                contracts,
                catalog,
                contract_paths,
                result,
            )?;
        } else if path.is_file() {
            // Skip files that are part of the Design System's own component implementation
            if contract_paths.contains(&rel) {
                continue;
            }
            scan_file_drift(base, &path, config, contracts, catalog, result)?;
        }
    }

    Ok(())
}

fn matches_ignore(rel: &str, ignore_patterns: &[String]) -> bool {
    for pat in ignore_patterns {
        let clean_pat = pat.trim();
        if let Some(suffix) = clean_pat.strip_prefix("**/") {
            if let Some(mid) = suffix.strip_suffix("/**") {
                if rel.contains(mid) {
                    return true;
                }
            } else if let Some(ext) = suffix.strip_prefix('*') {
                if rel.ends_with(ext) {
                    return true;
                }
            } else if rel.contains(suffix) {
                return true;
            }
        } else if let Some(prefix) = clean_pat.strip_suffix("/**") {
            if rel.starts_with(prefix) {
                return true;
            }
        } else if rel == clean_pat || rel.contains(clean_pat) {
            return true;
        }
    }
    false
}

fn scan_file_drift(
    base: &Path,
    path: &Path,
    config: &DesignDriftConfig,
    contracts: &HashMap<String, ComponentContract>,
    _catalog: &TokenCatalog,
    result: &mut DriftScanResult,
) -> Result<()> {
    let ext = path.extension().and_then(|e| e.to_str()).unwrap_or("");
    let is_ui_file = matches!(
        ext,
        "tsx" | "jsx" | "html" | "vue" | "swift" | "kt" | "css" | "scss"
    );
    if !is_ui_file {
        return Ok(());
    }

    let content = match fs::read_to_string(path) {
        Ok(c) => c,
        Err(_) => return Ok(()),
    };

    let rel_path = normalize_rel_path(base, path);

    // Multi-line comment state tracking
    let mut in_block_comment = false;

    // Line-by-line scanning
    for (line_idx, line) in content.lines().enumerate() {
        let line_num = line_idx + 1;
        let trimmed = line.trim();

        // Handle block comment markers
        if in_block_comment {
            if let Some(end_pos) = trimmed.find("*/") {
                in_block_comment = false;
                let remainder = &trimmed[end_pos + 2..];
                scan_line_for_drift(
                    remainder, &rel_path, line_num, ext, config, contracts, result,
                );
            }
            continue;
        }

        if trimmed.starts_with("/*") {
            if !trimmed.contains("*/") {
                in_block_comment = true;
            }
            continue;
        }

        // Skip single-line comments or lines with ignore directive
        if trimmed.starts_with("//")
            || trimmed.starts_with('#')
            || trimmed.starts_with('*')
            || trimmed.starts_with("<!--")
            || trimmed.contains("ignore-design-token")
            || trimmed.contains("ignore-design-drift")
        {
            continue;
        }

        // Strip inline comments if present
        let code_line = if let Some(pos) = line.find("//") {
            &line[..pos]
        } else {
            line
        };

        scan_line_for_drift(
            code_line, &rel_path, line_num, ext, config, contracts, result,
        );
    }

    Ok(())
}

fn scan_line_for_drift(
    line: &str,
    rel_path: &str,
    line_num: usize,
    ext: &str,
    config: &DesignDriftConfig,
    contracts: &HashMap<String, ComponentContract>,
    result: &mut DriftScanResult,
) {
    // 1. Hardcoded Hex Colors
    if let Some(hex) = find_hardcoded_hex(line) {
        result.violations.push(DesignLintViolation {
            file: rel_path.to_string(),
            line: line_num,
            rule: "no_hardcoded_color".to_string(),
            message: format!(
                "Hardcoded color '{}' detected. Use a W3C DTCG design token instead.",
                hex
            ),
            severity: "error".to_string(),
        });
    }

    // 2. Platform-specific primitive and component drift
    match ext {
        "tsx" | "jsx" | "html" | "vue" => {
            scan_web_line(line, rel_path, line_num, config, contracts, result);
        }
        "swift" => {
            scan_ios_line(line, rel_path, line_num, config, contracts, result);
        }
        "kt" => {
            scan_android_line(line, rel_path, line_num, config, contracts, result);
        }
        _ => {}
    }
}

fn scan_web_line(
    line: &str,
    rel_path: &str,
    line_num: usize,
    config: &DesignDriftConfig,
    contracts: &HashMap<String, ComponentContract>,
    result: &mut DriftScanResult,
) {
    let raw_primitives = config
        .raw_primitives
        .get("web")
        .cloned()
        .unwrap_or_else(|| {
            vec![
                "button".to_string(),
                "input".to_string(),
                "select".to_string(),
                "textarea".to_string(),
                "a".to_string(),
            ]
        });

    // Check for raw HTML tags e.g. <button, <input
    for prim in &raw_primitives {
        let pattern = format!("<{}", prim);
        if let Some(pos) = line.find(&pattern) {
            let next_char = line.as_bytes().get(pos + pattern.len()).copied();
            let is_boundary = matches!(
                next_char,
                Some(b' ' | b'>' | b'/' | b'\t' | b'\n' | b'\r') | None
            );

            if is_boundary {
                // Check if a registered contract exists for this primitive
                let matching_contract = contracts.keys().find(|c| c.eq_ignore_ascii_case(prim));
                if let Some(contract_name) = matching_contract {
                    result.raw_primitive_violations += 1;
                    let severity = if config.on_raw_primitive.eq_ignore_ascii_case("block") {
                        "error"
                    } else {
                        "warning"
                    };
                    result.violations.push(DesignLintViolation {
                        file: rel_path.to_string(),
                        line: line_num,
                        rule: "raw_primitive_violation".to_string(),
                        message: format!(
                            "Raw primitive '<{}>' detected. Use design system contract '{}' instead.",
                            prim, contract_name
                        ),
                        severity: severity.to_string(),
                    });
                }
            }
        }
    }

    // Check for exported UI components: export const Foo = ..., export function Foo(...)
    if config.flag_new_primitives {
        if let Some(comp) = extract_exported_web_component(line) {
            if is_potential_custom_component(&comp)
                && !contracts.keys().any(|c| c.eq_ignore_ascii_case(&comp))
                && !result.new_components.contains(&comp)
            {
                result.new_components.push(comp.clone());
                result.needs_design_review = true;
                let severity = if config.on_new_primitive.eq_ignore_ascii_case("block") {
                    "error"
                } else {
                    "warning"
                };
                result.violations.push(DesignLintViolation {
                    file: rel_path.to_string(),
                    line: line_num,
                    rule: "unregistered_component".to_string(),
                    message: format!(
                        "Exported UI component '{}' is not registered in design/contracts. Requires design review.",
                        comp
                    ),
                    severity: severity.to_string(),
                });
            }
        }
    }
}

fn scan_ios_line(
    line: &str,
    rel_path: &str,
    line_num: usize,
    config: &DesignDriftConfig,
    contracts: &HashMap<String, ComponentContract>,
    result: &mut DriftScanResult,
) {
    let raw_primitives = config
        .raw_primitives
        .get("ios")
        .cloned()
        .unwrap_or_else(|| {
            vec![
                "Button".to_string(),
                "TextField".to_string(),
                "SecureField".to_string(),
                "Toggle".to_string(),
            ]
        });

    for prim in &raw_primitives {
        if is_call_or_initializer(line, prim) {
            let matching_contract = contracts.keys().find(|c| c.eq_ignore_ascii_case(prim));
            if let Some(contract_name) = matching_contract {
                result.raw_primitive_violations += 1;
                let severity = if config.on_raw_primitive.eq_ignore_ascii_case("block") {
                    "error"
                } else {
                    "warning"
                };
                result.violations.push(DesignLintViolation {
                    file: rel_path.to_string(),
                    line: line_num,
                    rule: "raw_primitive_violation".to_string(),
                    message: format!(
                        "Raw SwiftUI primitive '{}' detected. Use design system contract '{}' instead.",
                        prim, contract_name
                    ),
                    severity: severity.to_string(),
                });
            }
        }
    }

    if config.flag_new_primitives {
        if let Some(comp) = extract_swift_view(line) {
            if is_potential_custom_component(&comp)
                && !contracts.keys().any(|c| c.eq_ignore_ascii_case(&comp))
                && !result.new_components.contains(&comp)
            {
                result.new_components.push(comp.clone());
                result.needs_design_review = true;
                let severity = if config.on_new_primitive.eq_ignore_ascii_case("block") {
                    "error"
                } else {
                    "warning"
                };
                result.violations.push(DesignLintViolation {
                    file: rel_path.to_string(),
                    line: line_num,
                    rule: "unregistered_component".to_string(),
                    message: format!(
                        "Exported SwiftUI component '{}' is not registered in design/contracts. Requires design review.",
                        comp
                    ),
                    severity: severity.to_string(),
                });
            }
        }
    }
}

fn scan_android_line(
    line: &str,
    rel_path: &str,
    line_num: usize,
    config: &DesignDriftConfig,
    contracts: &HashMap<String, ComponentContract>,
    result: &mut DriftScanResult,
) {
    let raw_primitives = config
        .raw_primitives
        .get("android")
        .cloned()
        .unwrap_or_else(|| {
            vec![
                "Button".to_string(),
                "TextField".to_string(),
                "OutlinedTextField".to_string(),
                "Switch".to_string(),
            ]
        });

    for prim in &raw_primitives {
        if is_call_or_initializer(line, prim) {
            let matching_contract = contracts.keys().find(|c| c.eq_ignore_ascii_case(prim));
            if let Some(contract_name) = matching_contract {
                result.raw_primitive_violations += 1;
                let severity = if config.on_raw_primitive.eq_ignore_ascii_case("block") {
                    "error"
                } else {
                    "warning"
                };
                result.violations.push(DesignLintViolation {
                    file: rel_path.to_string(),
                    line: line_num,
                    rule: "raw_primitive_violation".to_string(),
                    message: format!(
                        "Raw Compose primitive '{}' detected. Use design system contract '{}' instead.",
                        prim, contract_name
                    ),
                    severity: severity.to_string(),
                });
            }
        }
    }

    if config.flag_new_primitives {
        if let Some(comp) = extract_compose_view(line) {
            if is_potential_custom_component(&comp)
                && !contracts.keys().any(|c| c.eq_ignore_ascii_case(&comp))
                && !result.new_components.contains(&comp)
            {
                result.new_components.push(comp.clone());
                result.needs_design_review = true;
                let severity = if config.on_new_primitive.eq_ignore_ascii_case("block") {
                    "error"
                } else {
                    "warning"
                };
                result.violations.push(DesignLintViolation {
                    file: rel_path.to_string(),
                    line: line_num,
                    rule: "unregistered_component".to_string(),
                    message: format!(
                        "Exported Compose component '{}' is not registered in design/contracts. Requires design review.",
                        comp
                    ),
                    severity: severity.to_string(),
                });
            }
        }
    }
}

fn is_call_or_initializer(line: &str, symbol: &str) -> bool {
    let bytes = line.as_bytes();
    let symbol_bytes = symbol.as_bytes();
    let mut i = 0;

    while i + symbol_bytes.len() <= bytes.len() {
        if &bytes[i..i + symbol_bytes.len()] == symbol_bytes {
            let before_ok = if i == 0 {
                true
            } else {
                let prev = bytes[i - 1];
                !prev.is_ascii_alphanumeric() && prev != b'_' && prev != b'.'
            };

            let after_idx = i + symbol_bytes.len();
            let after_ok = if after_idx >= bytes.len() {
                false
            } else {
                let next = bytes[after_idx];
                next == b'(' || next == b' ' || next == b'{'
            };

            if before_ok && after_ok {
                // If next is space, verify next non-space is '(' or '{'
                if bytes[after_idx] == b' ' {
                    let mut k = after_idx;
                    while k < bytes.len() && bytes[k] == b' ' {
                        k += 1;
                    }
                    if k < bytes.len() && (bytes[k] == b'(' || bytes[k] == b'{') {
                        return true;
                    }
                } else {
                    return true;
                }
            }
        }
        i += 1;
    }

    false
}

fn extract_exported_web_component(line: &str) -> Option<String> {
    let trimmed = line.trim();
    let rest = trimmed.strip_prefix("export ")?;
    let rest = if let Some(stripped) = rest.strip_prefix("default ") {
        stripped.trim()
    } else {
        rest
    };

    let name = if let Some(stripped) = rest.strip_prefix("const ") {
        let after = stripped.trim();
        after.split([' ', ':', '=']).next()?
    } else if let Some(stripped) = rest.strip_prefix("function ") {
        let after = stripped.trim();
        after.split([' ', '(', '<']).next()?
    } else {
        let stripped = rest.strip_prefix("class ")?;
        let after = stripped.trim();
        after.split([' ', '{', '<']).next()?
    };

    if !name.is_empty()
        && name
            .chars()
            .next()
            .map(|c| c.is_uppercase())
            .unwrap_or(false)
    {
        Some(name.to_string())
    } else {
        None
    }
}

fn extract_swift_view(line: &str) -> Option<String> {
    let trimmed = line.trim();
    // e.g. struct FooView: View or public struct FooView: View
    if !trimmed.contains("struct ") && !trimmed.contains("class ") {
        return None;
    }
    if !trimmed.contains(": View") && !trimmed.contains(": UIView") {
        return None;
    }

    let tokens: Vec<&str> = trimmed.split_whitespace().collect();
    for i in 0..tokens.len() {
        if (tokens[i] == "struct" || tokens[i] == "class") && i + 1 < tokens.len() {
            let raw_name = tokens[i + 1];
            let name = raw_name.split(':').next()?.trim();
            if !name.is_empty()
                && name
                    .chars()
                    .next()
                    .map(|c| c.is_uppercase())
                    .unwrap_or(false)
            {
                return Some(name.to_string());
            }
        }
    }
    None
}

fn extract_compose_view(line: &str) -> Option<String> {
    let trimmed = line.trim();
    // @Composable fun FooView(...) or fun FooView(...) with @Composable preceding
    if trimmed.contains("fun ") {
        let after_fun = trimmed.split("fun ").nth(1)?.trim();
        let name = after_fun.split(['(', '<', ' ']).next()?.trim();
        if !name.is_empty()
            && name
                .chars()
                .next()
                .map(|c| c.is_uppercase())
                .unwrap_or(false)
        {
            return Some(name.to_string());
        }
    }
    None
}

fn is_potential_custom_component(name: &str) -> bool {
    let lower = name.to_lowercase();
    !(lower == "app"
        || lower == "root"
        || lower == "main"
        || lower.ends_with("preview")
        || lower.ends_with("previews")
        || lower.ends_with("test")
        || lower.ends_with("tests")
        || lower.ends_with("provider")
        || lower.ends_with("routes"))
}

pub fn find_hardcoded_hex(line: &str) -> Option<String> {
    let bytes = line.as_bytes();
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i] == b'#' {
            let start = i;
            let mut j = i + 1;
            while j < bytes.len() && bytes[j].is_ascii_hexdigit() {
                j += 1;
            }
            let len = j - start - 1;
            if (len == 3 || len == 6 || len == 8)
                && (j == bytes.len() || !bytes[j].is_ascii_alphanumeric())
            {
                let slice = &line[start..j];
                return Some(slice.to_string());
            }
            i = j;
        } else {
            i += 1;
        }
    }
    None
}

fn run_external_linter(root: &Path, command: &str) -> Result<Vec<DesignLintViolation>> {
    let mut violations = Vec::new();
    let output = Command::new("sh")
        .arg("-c")
        .arg(command)
        .current_dir(root)
        .output()
        .with_context(|| format!("Failed to execute external drift linter: {}", command))?;

    let stdout = String::from_utf8_lossy(&output.stdout);
    if let Ok(val) = serde_json::from_str::<serde_json::Value>(&stdout) {
        if let Some(arr) = val.as_array() {
            for item in arr {
                // Check if ESLint output format
                if let (Some(file_path), Some(messages)) = (
                    item.get("filePath").and_then(|f| f.as_str()),
                    item.get("messages").and_then(|m| m.as_array()),
                ) {
                    for msg in messages {
                        let line = msg.get("line").and_then(|l| l.as_u64()).unwrap_or(1) as usize;
                        let rule_id = msg
                            .get("ruleId")
                            .and_then(|r| r.as_str())
                            .unwrap_or("external_linter");
                        let message = msg.get("message").and_then(|m| m.as_str()).unwrap_or("");
                        let severity = match msg.get("severity").and_then(|s| s.as_u64()) {
                            Some(2) => "error",
                            _ => "warning",
                        };
                        violations.push(DesignLintViolation {
                            file: file_path.to_string(),
                            line,
                            rule: rule_id.to_string(),
                            message: message.to_string(),
                            severity: severity.to_string(),
                        });
                    }
                } else if let (Some(file), Some(rule), Some(message)) = (
                    item.get("file").and_then(|f| f.as_str()),
                    item.get("rule").and_then(|r| r.as_str()),
                    item.get("message").and_then(|m| m.as_str()),
                ) {
                    let line = item.get("line").and_then(|l| l.as_u64()).unwrap_or(1) as usize;
                    let severity = item
                        .get("severity")
                        .and_then(|s| s.as_str())
                        .unwrap_or("warning");
                    violations.push(DesignLintViolation {
                        file: file.to_string(),
                        line,
                        rule: rule.to_string(),
                        message: message.to_string(),
                        severity: severity.to_string(),
                    });
                }
            }
        }
    }

    Ok(violations)
}
