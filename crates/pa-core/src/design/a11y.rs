use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use std::fs;
use std::path::Path;
use std::process::Command;

use crate::schema::{AndroidPlatformSpec, DesignSystemConfig, IosPlatformSpec, WebPlatformSpec};

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct A11yViolation {
    #[serde(default)]
    pub platform: String,
    pub id: String,
    pub impact: String,
    pub description: String,
    pub help_url: Option<String>,
    pub nodes_count: usize,
    pub target: Option<String>,
}

impl A11yViolation {
    pub fn is_blocking(&self) -> bool {
        self.impact == "serious" || self.impact == "critical"
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct A11yExecutionReport {
    pub platform: String,
    pub passed: bool,
    pub violations: Vec<A11yViolation>,
    pub blocking_violations_count: usize,
    pub engine: String,
    pub wcag_level: String,
    pub message: String,
}

pub fn parse_axe_violations_json(
    json_str: &str,
    wcag_level: &str,
    platform: &str,
) -> Result<Vec<A11yViolation>> {
    let mut result = Vec::new();
    let val: serde_json::Value =
        serde_json::from_str(json_str).context("Failed to parse axe-core JSON")?;

    let violations = if let Some(arr) = val.get("violations").and_then(|v| v.as_array()) {
        arr
    } else if let Some(arr) = val.as_array() {
        arr
    } else {
        return Ok(result);
    };

    let target_level = wcag_level.to_uppercase();

    for item in violations {
        let id = item
            .get("id")
            .and_then(|v| v.as_str())
            .unwrap_or("unknown")
            .to_string();
        let impact = item
            .get("impact")
            .and_then(|v| v.as_str())
            .unwrap_or("unknown")
            .to_string();
        let description = item
            .get("description")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        let help_url = item
            .get("helpUrl")
            .and_then(|v| v.as_str())
            .map(|s| s.to_string());

        let tags: Vec<String> = item
            .get("tags")
            .and_then(|t| t.as_array())
            .map(|arr| {
                arr.iter()
                    .filter_map(|v| v.as_str().map(|s| s.to_lowercase()))
                    .collect()
            })
            .unwrap_or_default();

        let matches_level = match target_level.as_str() {
            "A" => tags
                .iter()
                .any(|t| t == "wcag2a" || t == "wcag21a" || t == "wcag22a"),
            "AA" => tags.iter().any(|t| {
                t == "wcag2a"
                    || t == "wcag2aa"
                    || t == "wcag21a"
                    || t == "wcag21aa"
                    || t == "wcag22a"
                    || t == "wcag22aa"
            }),
            "AAA" => tags.iter().any(|t| t.starts_with("wcag")),
            _ => true,
        };

        if !tags.is_empty() && !matches_level {
            continue;
        }

        let nodes = item.get("nodes").and_then(|n| n.as_array());
        let nodes_count = nodes.map(|n| n.len()).unwrap_or(0);
        let target = nodes
            .and_then(|n| n.first())
            .and_then(|node| node.get("target"))
            .and_then(|t| t.as_array())
            .and_then(|arr| arr.first())
            .and_then(|v| v.as_str())
            .map(|s| s.to_string());

        result.push(A11yViolation {
            platform: platform.to_string(),
            id,
            impact,
            description,
            help_url,
            nodes_count,
            target,
        });
    }

    Ok(result)
}

pub fn run_web_a11y(
    root: &Path,
    config: &WebPlatformSpec,
    base_config: &DesignSystemConfig,
) -> Result<A11yExecutionReport> {
    let has_node = Command::new("node").arg("--version").output().is_ok();
    let block_on_missing = config.on_missing_tool.eq_ignore_ascii_case("block")
        || base_config.on_missing_platform == "fail";

    if !has_node {
        if block_on_missing {
            return Ok(A11yExecutionReport {
                platform: "web".to_string(),
                passed: false,
                violations: Vec::new(),
                blocking_violations_count: 0,
                engine: config.a11y_engine.clone(),
                wcag_level: config.wcag_level.clone(),
                message: "Node.js / Web runtime is not available on host.".to_string(),
            });
        } else {
            return Ok(A11yExecutionReport {
                platform: "web".to_string(),
                passed: true,
                violations: Vec::new(),
                blocking_violations_count: 0,
                engine: config.a11y_engine.clone(),
                wcag_level: config.wcag_level.clone(),
                message: "Node.js runtime missing (skipped with warning).".to_string(),
            });
        }
    }

    let mut violations = Vec::new();
    let mut command_executed = false;

    if let Some(ref cmd_str) = config.a11y_command {
        let mut cmd = Command::new("sh");
        cmd.arg("-c")
            .arg(cmd_str)
            .current_dir(root)
            .env("HTTP_PROXY", "http://127.0.0.1:8080")
            .env("HTTPS_PROXY", "http://127.0.0.1:8080")
            .env("http_proxy", "http://127.0.0.1:8080")
            .env("https_proxy", "http://127.0.0.1:8080")
            .env("PA_BASELINE_DIR", &config.baseline_dir);

        if let Ok(o) = cmd.output() {
            command_executed = true;
            let stdout = String::from_utf8_lossy(&o.stdout);
            if let Ok(vulns) = parse_axe_violations_json(&stdout, &config.wcag_level, "web") {
                violations.extend(vulns);
            }
        }
    }

    if !command_executed || violations.is_empty() {
        let candidates = [
            root.join("target/a11y-results.json"),
            root.join(".pa/a11y-results.json"),
            root.join(".pa/reports/web-a11y.json"),
        ];

        for path in &candidates {
            if path.is_file() {
                if let Ok(content) = fs::read_to_string(path) {
                    if let Ok(vulns) =
                        parse_axe_violations_json(&content, &config.wcag_level, "web")
                    {
                        for v in vulns {
                            if !violations
                                .iter()
                                .any(|existing| existing.id == v.id && existing.target == v.target)
                            {
                                violations.push(v);
                            }
                        }
                        break;
                    }
                }
            }
        }
    }

    let blocking_violations_count = violations.iter().filter(|v| v.is_blocking()).count();
    let passed = blocking_violations_count == 0;
    let message = if passed {
        format!(
            "Web accessibility checks passed (WCAG {}, violations: {})",
            config.wcag_level,
            violations.len()
        )
    } else {
        format!(
            "Web accessibility checks failed (WCAG {}, {} blocking violations)",
            config.wcag_level, blocking_violations_count
        )
    };

    Ok(A11yExecutionReport {
        platform: "web".to_string(),
        passed,
        violations,
        blocking_violations_count,
        engine: config.a11y_engine.clone(),
        wcag_level: config.wcag_level.clone(),
        message,
    })
}

pub fn run_ios_a11y(
    root: &Path,
    config: &IosPlatformSpec,
    _base_config: &DesignSystemConfig,
) -> Result<A11yExecutionReport> {
    if !config.enabled {
        return Ok(A11yExecutionReport {
            platform: "ios".to_string(),
            passed: true,
            violations: Vec::new(),
            blocking_violations_count: 0,
            engine: config.a11y_engine.clone(),
            wcag_level: "iOS-Accessibility".to_string(),
            message: "iOS platform disabled in configuration.".to_string(),
        });
    }

    let has_simctl = Command::new("xcrun")
        .args(["simctl", "help"])
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false);

    let is_darwin = cfg!(target_os = "macos");
    let candidates = [
        root.join("target/ios-a11y-results.json"),
        root.join(".pa/reports/ios-a11y.json"),
    ];
    let has_reports = candidates.iter().any(|c| c.is_file());
    let has_command = config.a11y_command.is_some();

    if (!has_simctl || !is_darwin) && !has_reports && !has_command {
        let block = config.on_missing_platform.eq_ignore_ascii_case("block");
        return Ok(A11yExecutionReport {
            platform: "ios".to_string(),
            passed: !block,
            violations: Vec::new(),
            blocking_violations_count: 0,
            engine: config.a11y_engine.clone(),
            wcag_level: "iOS-Accessibility".to_string(),
            message: if block {
                "iOS verification blocked: 'simctl' / Xcode CLI is not available.".to_string()
            } else {
                "iOS verification skipped: 'simctl' / Xcode CLI is not available.".to_string()
            },
        });
    }

    let mut violations = Vec::new();
    if let Some(ref cmd_str) = config.a11y_command {
        let mut cmd = Command::new("sh");
        cmd.arg("-c")
            .arg(cmd_str)
            .current_dir(root)
            .env("SIMCTL_CHILD_HTTP_PROXY", "http://127.0.0.1:8080")
            .env("SIMCTL_CHILD_HTTPS_PROXY", "http://127.0.0.1:8080")
            .env("HTTP_PROXY", "http://127.0.0.1:8080")
            .env("HTTPS_PROXY", "http://127.0.0.1:8080")
            .env("http_proxy", "http://127.0.0.1:8080")
            .env("https_proxy", "http://127.0.0.1:8080")
            .env("PA_BASELINE_DIR", &config.baseline_dir);

        if let Ok(o) = cmd.output() {
            let stdout = String::from_utf8_lossy(&o.stdout);
            let stderr = String::from_utf8_lossy(&o.stderr);
            let combined = format!("{}\n{}", stdout, stderr);
            violations.extend(parse_ios_a11y_output(&combined));
        }
    }

    for path in &candidates {
        if path.is_file() {
            if let Ok(content) = fs::read_to_string(path) {
                let parsed = parse_ios_a11y_output(&content);
                for v in parsed {
                    if !violations
                        .iter()
                        .any(|existing| existing.id == v.id && existing.target == v.target)
                    {
                        violations.push(v);
                    }
                }
            }
        }
    }

    let blocking_violations_count = violations.iter().filter(|v| v.is_blocking()).count();
    let passed = blocking_violations_count == 0;
    let message = if passed {
        format!(
            "iOS accessibility checks passed (violations: {})",
            violations.len()
        )
    } else {
        format!(
            "iOS accessibility checks failed ({} blocking violations)",
            blocking_violations_count
        )
    };

    Ok(A11yExecutionReport {
        platform: "ios".to_string(),
        passed,
        violations,
        blocking_violations_count,
        engine: config.a11y_engine.clone(),
        wcag_level: "iOS-Accessibility".to_string(),
        message,
    })
}

pub fn parse_ios_a11y_output(raw: &str) -> Vec<A11yViolation> {
    let mut result = Vec::new();

    if let Ok(val) = serde_json::from_str::<serde_json::Value>(raw) {
        let arr = val
            .as_array()
            .cloned()
            .or_else(|| val.get("violations").and_then(|v| v.as_array()).cloned());
        if let Some(violations) = arr {
            for item in violations {
                let id = item
                    .get("id")
                    .and_then(|v| v.as_str())
                    .unwrap_or("xctest_a11y")
                    .to_string();
                let impact = item
                    .get("impact")
                    .and_then(|v| v.as_str())
                    .unwrap_or("serious")
                    .to_string();
                let description = item
                    .get("description")
                    .and_then(|v| v.as_str())
                    .unwrap_or("iOS accessibility audit issue")
                    .to_string();
                let target = item
                    .get("target")
                    .and_then(|v| v.as_str())
                    .map(|s| s.to_string());

                result.push(A11yViolation {
                    platform: "ios".to_string(),
                    id,
                    impact,
                    description,
                    help_url: None,
                    nodes_count: 1,
                    target,
                });
            }
            return result;
        }
    }

    for line in raw.lines() {
        let trimmed = line.trim();
        if trimmed.contains("AccessibilityAudit")
            && (trimmed.contains("failed") || trimmed.contains("issue"))
        {
            let target = if let Some(pos) = trimmed.find("element:") {
                let sub = &trimmed[pos + 8..];
                sub.split(',').next().map(|s| s.trim().to_string())
            } else {
                None
            };

            result.push(A11yViolation {
                platform: "ios".to_string(),
                id: "xctest_accessibility_audit".to_string(),
                impact: "serious".to_string(),
                description: trimmed.to_string(),
                help_url: None,
                nodes_count: 1,
                target,
            });
        }
    }

    result
}

pub fn run_android_a11y(
    root: &Path,
    config: &AndroidPlatformSpec,
    _base_config: &DesignSystemConfig,
) -> Result<A11yExecutionReport> {
    if !config.enabled {
        return Ok(A11yExecutionReport {
            platform: "android".to_string(),
            passed: true,
            violations: Vec::new(),
            blocking_violations_count: 0,
            engine: config.a11y_engine.clone(),
            wcag_level: "Android-Accessibility".to_string(),
            message: "Android platform disabled in configuration.".to_string(),
        });
    }

    let has_adb = Command::new("adb")
        .arg("version")
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false)
        || std::env::var("ANDROID_HOME").is_ok()
        || std::env::var("ANDROID_SDK_ROOT").is_ok()
        || root.join("gradlew").is_file();

    let candidates = [
        root.join("target/android-a11y-results.json"),
        root.join(".pa/reports/android-a11y.json"),
    ];
    let has_reports = candidates.iter().any(|c| c.is_file());
    let has_command = config.a11y_command.is_some();

    if !has_adb && !has_reports && !has_command {
        let block = config.on_missing_platform.eq_ignore_ascii_case("block");
        return Ok(A11yExecutionReport {
            platform: "android".to_string(),
            passed: !block,
            violations: Vec::new(),
            blocking_violations_count: 0,
            engine: config.a11y_engine.clone(),
            wcag_level: "Android-Accessibility".to_string(),
            message: if block {
                "Android verification blocked: 'adb' / Android SDK is not available.".to_string()
            } else {
                "Android verification skipped: 'adb' / Android SDK is not available.".to_string()
            },
        });
    }

    let mut violations = Vec::new();
    if let Some(ref cmd_str) = config.a11y_command {
        let mut cmd = Command::new("sh");
        cmd.arg("-c")
            .arg(cmd_str)
            .current_dir(root)
            .env("HTTP_PROXY", "http://127.0.0.1:8080")
            .env("HTTPS_PROXY", "http://127.0.0.1:8080")
            .env("http_proxy", "http://127.0.0.1:8080")
            .env("https_proxy", "http://127.0.0.1:8080")
            .env("PA_BASELINE_DIR", &config.baseline_dir);

        if let Ok(o) = cmd.output() {
            let stdout = String::from_utf8_lossy(&o.stdout);
            let stderr = String::from_utf8_lossy(&o.stderr);
            let combined = format!("{}\n{}", stdout, stderr);
            violations.extend(parse_android_a11y_output(&combined));
        }
    }

    for path in &candidates {
        if path.is_file() {
            if let Ok(content) = fs::read_to_string(path) {
                let parsed = parse_android_a11y_output(&content);
                for v in parsed {
                    if !violations
                        .iter()
                        .any(|existing| existing.id == v.id && existing.target == v.target)
                    {
                        violations.push(v);
                    }
                }
            }
        }
    }

    let blocking_violations_count = violations.iter().filter(|v| v.is_blocking()).count();
    let passed = blocking_violations_count == 0;
    let message = if passed {
        format!(
            "Android accessibility checks passed (violations: {})",
            violations.len()
        )
    } else {
        format!(
            "Android accessibility checks failed ({} blocking violations)",
            blocking_violations_count
        )
    };

    Ok(A11yExecutionReport {
        platform: "android".to_string(),
        passed,
        violations,
        blocking_violations_count,
        engine: config.a11y_engine.clone(),
        wcag_level: "Android-Accessibility".to_string(),
        message,
    })
}

pub fn parse_android_a11y_output(raw: &str) -> Vec<A11yViolation> {
    let mut result = Vec::new();

    if let Ok(val) = serde_json::from_str::<serde_json::Value>(raw) {
        let arr = val
            .as_array()
            .cloned()
            .or_else(|| val.get("violations").and_then(|v| v.as_array()).cloned());
        if let Some(violations) = arr {
            for item in violations {
                let id = item
                    .get("id")
                    .and_then(|v| v.as_str())
                    .unwrap_or("espresso_a11y")
                    .to_string();
                let impact = item
                    .get("impact")
                    .and_then(|v| v.as_str())
                    .unwrap_or("serious")
                    .to_string();
                let description = item
                    .get("description")
                    .and_then(|v| v.as_str())
                    .unwrap_or("Android accessibility check failure")
                    .to_string();
                let target = item
                    .get("target")
                    .and_then(|v| v.as_str())
                    .map(|s| s.to_string());

                result.push(A11yViolation {
                    platform: "android".to_string(),
                    id,
                    impact,
                    description,
                    help_url: None,
                    nodes_count: 1,
                    target,
                });
            }
            return result;
        }
    }

    for line in raw.lines() {
        let trimmed = line.trim();
        if trimmed.contains("AccessibilityCheck")
            || trimmed.contains("AccessibilityViewCheckException")
        {
            let target = if let Some(pos) = trimmed.find("View: ") {
                let sub = &trimmed[pos + 6..];
                sub.split(';').next().map(|s| s.trim().to_string())
            } else {
                None
            };

            result.push(A11yViolation {
                platform: "android".to_string(),
                id: "espresso_accessibility_check".to_string(),
                impact: "serious".to_string(),
                description: trimmed.to_string(),
                help_url: None,
                nodes_count: 1,
                target,
            });
        }
    }

    result
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_axe_violations_clean_and_violations() {
        let clean_json = r#"{"violations": []}"#;
        let res = parse_axe_violations_json(clean_json, "AA", "web").unwrap();
        assert!(res.is_empty());

        let mixed_json = r#"{
            "violations": [
                {
                    "id": "color-contrast",
                    "impact": "serious",
                    "tags": ["cat.color", "wcag2aa"],
                    "description": "Elements must have sufficient color contrast",
                    "helpUrl": "https://dequeuniversity.com/rules/axe/4.4/color-contrast",
                    "nodes": [
                        { "target": [".btn-primary"] }
                    ]
                },
                {
                    "id": "focus-order-semantics",
                    "impact": "minor",
                    "tags": ["wcag2a"],
                    "description": "Focus order test",
                    "nodes": []
                },
                {
                    "id": "aaa-only-rule",
                    "impact": "critical",
                    "tags": ["wcag2aaa"],
                    "description": "Requires enhanced contrast",
                    "nodes": []
                }
            ]
        }"#;

        // When evaluating for WCAG AA, 'aaa-only-rule' should be filtered out
        let res_aa = parse_axe_violations_json(mixed_json, "AA", "web").unwrap();
        assert_eq!(res_aa.len(), 2);
        assert_eq!(res_aa[0].id, "color-contrast");
        assert_eq!(res_aa[0].impact, "serious");
        assert_eq!(res_aa[0].platform, "web");
        assert_eq!(res_aa[0].target.as_deref(), Some(".btn-primary"));
        assert!(res_aa[0].is_blocking());
        assert_eq!(res_aa[1].id, "focus-order-semantics");
        assert!(!res_aa[1].is_blocking());

        // When evaluating for WCAG AAA, all 3 should match
        let res_aaa = parse_axe_violations_json(mixed_json, "AAA", "web").unwrap();
        assert_eq!(res_aaa.len(), 3);

        // When evaluating for WCAG A, only 'focus-order-semantics' and 'color-contrast' (if contains wcag2a)
        let res_a = parse_axe_violations_json(mixed_json, "A", "web").unwrap();
        assert_eq!(res_a.len(), 1);
        assert_eq!(res_a[0].id, "focus-order-semantics");
    }

    #[test]
    fn test_parse_ios_a11y_json_and_text() {
        let json_str = r#"[
            {
                "id": "hit_target_size",
                "impact": "critical",
                "description": "Button touch target smaller than 44x44pt",
                "target": "SubmitButton"
            }
        ]"#;
        let violations = parse_ios_a11y_output(json_str);
        assert_eq!(violations.len(), 1);
        assert_eq!(violations[0].platform, "ios");
        assert_eq!(violations[0].id, "hit_target_size");
        assert!(violations[0].is_blocking());

        let text_output =
            "XCTest AccessibilityAudit failed on element: BackButton, reason: missing label";
        let text_v = parse_ios_a11y_output(text_output);
        assert_eq!(text_v.len(), 1);
        assert_eq!(text_v[0].target.as_deref(), Some("BackButton"));
        assert_eq!(text_v[0].platform, "ios");
    }

    #[test]
    fn test_parse_android_a11y_json_and_text() {
        let json_str = r#"[
            {
                "id": "content_description_missing",
                "impact": "serious",
                "description": "ImageView missing contentDescription",
                "target": "logoImageView"
            }
        ]"#;
        let violations = parse_android_a11y_output(json_str);
        assert_eq!(violations.len(), 1);
        assert_eq!(violations[0].platform, "android");
        assert_eq!(violations[0].id, "content_description_missing");
        assert!(violations[0].is_blocking());

        let text_output =
            "AccessibilityCheck failed: View: submitBtn; Issue: Touch target too small";
        let text_v = parse_android_a11y_output(text_output);
        assert_eq!(text_v.len(), 1);
        assert_eq!(text_v[0].target.as_deref(), Some("submitBtn"));
        assert_eq!(text_v[0].platform, "android");
    }
}
