use anyhow::Result;
use std::fs;
use std::path::Path;
use std::process::Command;

use crate::schema::{AndroidPlatformSpec, DesignSystemConfig};

use super::{A11yViolation, PlatformGateResult, VisualDiffFailure};

pub struct AndroidEvaluationResult {
    pub gate_result: PlatformGateResult,
    pub a11y_violations: Vec<A11yViolation>,
    pub visual_diff_failures: Vec<VisualDiffFailure>,
}

pub fn evaluate_android_platform(
    root: &Path,
    config: &AndroidPlatformSpec,
    _base_config: &DesignSystemConfig,
) -> Result<AndroidEvaluationResult> {
    if !config.enabled {
        return Ok(AndroidEvaluationResult {
            gate_result: PlatformGateResult {
                platform: "android".to_string(),
                status: "skipped".to_string(),
                message: "Android platform disabled in configuration.".to_string(),
                details: Vec::new(),
            },
            a11y_violations: Vec::new(),
            visual_diff_failures: Vec::new(),
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

    let a11y_file = root.join("target/android-a11y-results.json");
    let a11y_file_pa = root.join(".pa/reports/android-a11y.json");
    let a11y_path = if a11y_file.is_file() {
        Some(a11y_file)
    } else if a11y_file_pa.is_file() {
        Some(a11y_file_pa)
    } else {
        None
    };

    let visual_file = root.join("target/android-visual-diff-results.json");
    let visual_file_pa = root.join(".pa/reports/android-visual-diff.json");
    let visual_path = if visual_file.is_file() {
        Some(visual_file)
    } else if visual_file_pa.is_file() {
        Some(visual_file_pa)
    } else {
        None
    };

    let has_reports = a11y_path.is_some() || visual_path.is_some();
    let has_commands = config.a11y_command.is_some() || config.visual_diff_command.is_some();

    if !has_adb && !has_reports && !has_commands {
        if config.on_missing_platform.eq_ignore_ascii_case("block") {
            return Ok(AndroidEvaluationResult {
                gate_result: PlatformGateResult {
                    platform: "android".to_string(),
                    status: "failed".to_string(),
                    message: "Android verification enabled but 'adb' / Android SDK is not available."
                        .to_string(),
                    details: vec![
                        "Prerequisite failed (on_missing_platform = 'block'): Android SDK / adb / gradlew required."
                            .to_string(),
                    ],
                },
                a11y_violations: Vec::new(),
                visual_diff_failures: Vec::new(),
            });
        } else {
            return Ok(AndroidEvaluationResult {
                gate_result: PlatformGateResult {
                    platform: "android".to_string(),
                    status: "skipped".to_string(),
                    message: "Android verification skipped: 'adb' / Android SDK is not available."
                        .to_string(),
                    details: Vec::new(),
                },
                a11y_violations: Vec::new(),
                visual_diff_failures: Vec::new(),
            });
        }
    }

    let mut a11y_violations = Vec::new();
    let mut visual_diff_failures = Vec::new();
    let mut details = Vec::new();
    let mut passed = true;

    // 1. Accessibility Verification (Espresso a11y / Compose semantics)
    if let Some(ref cmd_str) = config.a11y_command {
        let mut cmd = Command::new("sh");
        cmd.arg("-c").arg(cmd_str).current_dir(root);

        // Inject proxy settings for proxy isolation
        cmd.env("HTTP_PROXY", "http://127.0.0.1:8080")
            .env("HTTPS_PROXY", "http://127.0.0.1:8080")
            .env("http_proxy", "http://127.0.0.1:8080")
            .env("https_proxy", "http://127.0.0.1:8080")
            .env("PA_BASELINE_DIR", &config.baseline_dir);

        if let Ok(o) = cmd.output() {
            let stdout = String::from_utf8_lossy(&o.stdout);
            let stderr = String::from_utf8_lossy(&o.stderr);
            let combined = format!("{}\n{}", stdout, stderr);
            let parsed = parse_android_a11y_output(&combined);
            a11y_violations.extend(parsed);
        }
    }

    let a11y_file = root.join("target/android-a11y-results.json");
    let a11y_file_pa = root.join(".pa/reports/android-a11y.json");
    let a11y_path = if a11y_file.is_file() {
        Some(a11y_file)
    } else if a11y_file_pa.is_file() {
        Some(a11y_file_pa)
    } else {
        None
    };

    if let Some(p) = a11y_path {
        if let Ok(content) = fs::read_to_string(&p) {
            let parsed = parse_android_a11y_output(&content);
            for v in parsed {
                if !a11y_violations
                    .iter()
                    .any(|existing| existing.id == v.id && existing.target == v.target)
                {
                    a11y_violations.push(v);
                }
            }
        }
    }

    for v in &a11y_violations {
        if v.impact == "serious" || v.impact == "critical" {
            passed = false;
        }
    }

    // 2. Visual Regression Verification (Paparazzi / Roborazzi or adb screencap)
    if let Some(ref cmd_str) = config.visual_diff_command {
        let mut cmd = Command::new("sh");
        cmd.arg("-c").arg(cmd_str).current_dir(root);
        cmd.env("HTTP_PROXY", "http://127.0.0.1:8080")
            .env("HTTPS_PROXY", "http://127.0.0.1:8080")
            .env("http_proxy", "http://127.0.0.1:8080")
            .env("https_proxy", "http://127.0.0.1:8080")
            .env("PA_BASELINE_DIR", &config.baseline_dir);

        if let Ok(o) = cmd.output() {
            let stdout = String::from_utf8_lossy(&o.stdout);
            let parsed = parse_android_visual_diff_output(&stdout, config.max_visual_diff_pct);
            visual_diff_failures.extend(parsed);
        }
    }

    if let Some(p) = visual_path {
        if let Ok(content) = fs::read_to_string(&p) {
            let parsed = parse_android_visual_diff_output(&content, config.max_visual_diff_pct);
            for f in parsed {
                if !visual_diff_failures
                    .iter()
                    .any(|existing| existing.snapshot_name == f.snapshot_name)
                {
                    visual_diff_failures.push(f);
                }
            }
        }
    }

    if !visual_diff_failures.is_empty() {
        passed = false;
    }

    details.push(format!(
        "Accessibility (engine: {}, violations: {})",
        config.a11y_engine,
        a11y_violations.len()
    ));
    details.push(format!(
        "Visual Regression (tool: {}, max_diff: {:.1}%, failures: {})",
        config.visual_diff_tool,
        config.max_visual_diff_pct * 100.0,
        visual_diff_failures.len()
    ));

    Ok(AndroidEvaluationResult {
        gate_result: PlatformGateResult {
            platform: "android".to_string(),
            status: if passed {
                "passed".to_string()
            } else {
                "failed".to_string()
            },
            message: format!(
                "Android platform active (runner: {}, a11y: {}, visual: {})",
                config.runner, config.a11y_engine, config.visual_diff_tool
            ),
            details,
        },
        a11y_violations,
        visual_diff_failures,
    })
}

pub fn parse_android_a11y_output(raw: &str) -> Vec<A11yViolation> {
    let mut result = Vec::new();

    if let Ok(val) = serde_json::from_str::<serde_json::Value>(raw) {
        let arr = val
            .as_array()
            .cloned()
            .or_else(|| val.get("violations").and_then(|v| v.as_array()).cloned());

        if let Some(items) = arr {
            for item in items {
                let id = item
                    .get("id")
                    .and_then(|v| v.as_str())
                    .unwrap_or("android_a11y_violation")
                    .to_string();
                let impact = item
                    .get("impact")
                    .and_then(|v| v.as_str())
                    .unwrap_or("serious")
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
                let target = item
                    .get("target")
                    .and_then(|v| v.as_str())
                    .map(|s| s.to_string());
                result.push(A11yViolation {
                    id,
                    impact,
                    description,
                    help_url,
                    nodes_count: 1,
                    target,
                });
            }
            return result;
        }
    }

    // Parse Gradle / Espresso / Compose accessibility failure lines
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

pub fn parse_android_visual_diff_output(raw: &str, max_pct: f64) -> Vec<VisualDiffFailure> {
    let mut failures = Vec::new();

    if let Ok(val) = serde_json::from_str::<serde_json::Value>(raw) {
        if let Some(arr) = val.as_array() {
            for item in arr {
                let name = item
                    .get("snapshot")
                    .or_else(|| item.get("name"))
                    .and_then(|v| v.as_str())
                    .unwrap_or("snapshot");
                let diff_pct = item
                    .get("diff_pct")
                    .or_else(|| item.get("diffPercentage"))
                    .and_then(|v| v.as_f64())
                    .unwrap_or(0.0);
                let baseline = item.get("baseline").and_then(|v| v.as_str()).unwrap_or("");
                let current = item.get("current").and_then(|v| v.as_str()).unwrap_or("");

                if diff_pct > max_pct {
                    failures.push(VisualDiffFailure {
                        snapshot_name: name.to_string(),
                        diff_pct,
                        max_allowed_pct: max_pct,
                        baseline_path: baseline.to_string(),
                        current_path: current.to_string(),
                    });
                }
            }
            return failures;
        }
    }

    // Paparazzi test failure output: "Paparazzi verification failed for [snapshot]: diff percentage was 0.07"
    for line in raw.lines() {
        if line.contains("Paparazzi verification failed")
            || line.contains("Roborazzi diff detected")
        {
            let diff_pct = if let Some(pos) = line.find("diff percentage was ") {
                let sub = &line[pos + 20..];
                sub.split_whitespace()
                    .next()
                    .and_then(|s| s.trim_end_matches('%').parse::<f64>().ok())
                    .map(|v| if v > 1.0 { v / 100.0 } else { v })
                    .unwrap_or(max_pct + 0.01)
            } else {
                max_pct + 0.01
            };

            let name = if let Some(start) = line.find('[') {
                if let Some(end) = line[start..].find(']') {
                    line[start + 1..start + end].to_string()
                } else {
                    "android_snapshot".to_string()
                }
            } else {
                "android_snapshot".to_string()
            };

            if diff_pct > max_pct {
                failures.push(VisualDiffFailure {
                    snapshot_name: name,
                    diff_pct,
                    max_allowed_pct: max_pct,
                    baseline_path: "".to_string(),
                    current_path: "".to_string(),
                });
            }
        }
    }

    failures
}
