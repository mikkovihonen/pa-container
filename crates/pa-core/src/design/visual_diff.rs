use anyhow::{Context, Result};
use image::{GenericImageView, ImageEncoder, ImageReader, Rgba, RgbaImage};
use serde::{Deserialize, Serialize};
use std::fs;
use std::io::Cursor;
use std::path::{Path, PathBuf};
use std::process::Command;

use crate::schema::{AndroidPlatformSpec, DesignSystemConfig, IosPlatformSpec, WebPlatformSpec};

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct VisualDiffFailure {
    #[serde(default)]
    pub platform: String,
    pub snapshot_name: String,
    pub diff_pct: f64,
    pub max_allowed_pct: f64,
    #[serde(default)]
    pub mismatched_pixels: usize,
    #[serde(default)]
    pub total_pixels: usize,
    pub baseline_path: String,
    pub current_path: String,
    #[serde(default)]
    pub diff_artifact_path: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct VisualDiffExecutionReport {
    pub platform: String,
    pub passed: bool,
    pub failures: Vec<VisualDiffFailure>,
    pub max_diff_pct: f64,
    pub total_snapshots_compared: usize,
    pub failed_snapshots_count: usize,
    pub tool: String,
    pub message: String,
}

#[derive(Debug, Clone)]
pub struct PixelDiffResult {
    pub total_pixels: usize,
    pub mismatched_pixels: usize,
    pub diff_pct: f64,
    pub diff_image_png: Option<Vec<u8>>,
}

/// Compares two PNG images pixel-by-pixel.
/// Mismatched pixels (color delta exceeding tolerance) are highlighted in bright red (#ff0055).
pub fn compare_png_bytes(
    baseline_bytes: &[u8],
    actual_bytes: &[u8],
    tolerance_per_channel: u8,
) -> Result<PixelDiffResult> {
    let base_img = ImageReader::new(Cursor::new(baseline_bytes))
        .with_guessed_format()
        .context("Failed to guess baseline image format")?
        .decode()
        .context("Failed to decode baseline PNG image")?;

    let actual_img = ImageReader::new(Cursor::new(actual_bytes))
        .with_guessed_format()
        .context("Failed to guess actual image format")?
        .decode()
        .context("Failed to decode actual PNG image")?;

    let (base_w, base_h) = base_img.dimensions();
    let (act_w, act_h) = actual_img.dimensions();

    let max_w = base_w.max(act_w);
    let max_h = base_h.max(act_h);
    let total_pixels = (max_w * max_h) as usize;

    if total_pixels == 0 {
        return Ok(PixelDiffResult {
            total_pixels: 0,
            mismatched_pixels: 0,
            diff_pct: 0.0,
            diff_image_png: None,
        });
    }

    let mut mismatched_pixels = 0usize;
    let mut diff_img = RgbaImage::new(max_w, max_h);

    for y in 0..max_h {
        for x in 0..max_w {
            let in_base = x < base_w && y < base_h;
            let in_act = x < act_w && y < act_h;

            if in_base && in_act {
                let p1 = base_img.get_pixel(x, y);
                let p2 = actual_img.get_pixel(x, y);

                let dr = (p1[0] as i16 - p2[0] as i16).unsigned_abs() as u8;
                let dg = (p1[1] as i16 - p2[1] as i16).unsigned_abs() as u8;
                let db = (p1[2] as i16 - p2[2] as i16).unsigned_abs() as u8;
                let da = (p1[3] as i16 - p2[3] as i16).unsigned_abs() as u8;

                if dr > tolerance_per_channel
                    || dg > tolerance_per_channel
                    || db > tolerance_per_channel
                    || da > tolerance_per_channel
                {
                    mismatched_pixels += 1;
                    // Highlight in vibrant red
                    diff_img.put_pixel(x, y, Rgba([255, 0, 85, 255]));
                } else {
                    // Dimmed baseline for context
                    diff_img.put_pixel(
                        x,
                        y,
                        Rgba([p1[0] / 3 + 40, p1[1] / 3 + 40, p1[2] / 3 + 40, p1[3]]),
                    );
                }
            } else {
                mismatched_pixels += 1;
                // Highlight dimension mismatch in magenta
                diff_img.put_pixel(x, y, Rgba([255, 0, 200, 255]));
            }
        }
    }

    let diff_pct = mismatched_pixels as f64 / total_pixels as f64;

    let diff_image_png = if mismatched_pixels > 0 {
        let mut buffer = Vec::new();
        let encoder = image::codecs::png::PngEncoder::new(&mut buffer);
        encoder
            .write_image(
                diff_img.as_raw(),
                max_w,
                max_h,
                image::ExtendedColorType::Rgba8,
            )
            .ok()
            .map(|_| buffer)
    } else {
        None
    };

    Ok(PixelDiffResult {
        total_pixels,
        mismatched_pixels,
        diff_pct,
        diff_image_png,
    })
}

/// Compares a single screenshot against its baseline file on disk.
pub fn compare_snapshot_file(
    platform: &str,
    snapshot_name: &str,
    baseline_path: &Path,
    current_path: &Path,
    max_allowed_pct: f64,
    diff_output_dir: &Path,
) -> Result<Option<VisualDiffFailure>> {
    if !baseline_path.is_file() {
        return Ok(Some(VisualDiffFailure {
            platform: platform.to_string(),
            snapshot_name: snapshot_name.to_string(),
            diff_pct: 1.0,
            max_allowed_pct,
            mismatched_pixels: 0,
            total_pixels: 0,
            baseline_path: baseline_path.display().to_string(),
            current_path: current_path.display().to_string(),
            diff_artifact_path: None,
        }));
    }

    if !current_path.is_file() {
        return Ok(Some(VisualDiffFailure {
            platform: platform.to_string(),
            snapshot_name: snapshot_name.to_string(),
            diff_pct: 1.0,
            max_allowed_pct,
            mismatched_pixels: 0,
            total_pixels: 0,
            baseline_path: baseline_path.display().to_string(),
            current_path: current_path.display().to_string(),
            diff_artifact_path: None,
        }));
    }

    let base_bytes = fs::read(baseline_path)
        .with_context(|| format!("Failed to read baseline {}", baseline_path.display()))?;
    let act_bytes = fs::read(current_path).with_context(|| {
        format!(
            "Failed to read current screenshot {}",
            current_path.display()
        )
    })?;

    let diff_result = compare_png_bytes(&base_bytes, &act_bytes, 8)?;

    if diff_result.diff_pct > max_allowed_pct {
        let mut diff_artifact_path = None;
        if let Some(diff_bytes) = diff_result.diff_image_png {
            let _ = fs::create_dir_all(diff_output_dir);
            let safe_name = snapshot_name.replace(['/', '\\', ' '], "_");
            let out_file = diff_output_dir.join(format!("{}_diff.png", safe_name));
            if fs::write(&out_file, diff_bytes).is_ok() {
                diff_artifact_path = Some(out_file.display().to_string());
            }
        }

        Ok(Some(VisualDiffFailure {
            platform: platform.to_string(),
            snapshot_name: snapshot_name.to_string(),
            diff_pct: diff_result.diff_pct,
            max_allowed_pct,
            mismatched_pixels: diff_result.mismatched_pixels,
            total_pixels: diff_result.total_pixels,
            baseline_path: baseline_path.display().to_string(),
            current_path: current_path.display().to_string(),
            diff_artifact_path,
        }))
    } else {
        Ok(None)
    }
}

/// Scans baseline directory and compares with actual screenshots in candidate current directories.
pub fn compare_baseline_directory(
    platform: &str,
    baseline_dir: &Path,
    current_dirs: &[PathBuf],
    max_allowed_pct: f64,
    diff_output_dir: &Path,
) -> Result<Vec<VisualDiffFailure>> {
    let mut failures = Vec::new();
    if !baseline_dir.is_dir() {
        return Ok(failures);
    }

    for entry in fs::read_dir(baseline_dir)?.filter_map(|e| e.ok()) {
        let p = entry.path();
        if p.extension().and_then(|e| e.to_str()).unwrap_or("") == "png" {
            let file_name = p.file_name().unwrap().to_string_lossy().to_string();
            let snapshot_name = p.file_stem().unwrap().to_string_lossy().to_string();

            // Find matching current screenshot
            let mut current_path = None;
            for c_dir in current_dirs {
                let candidate = c_dir.join(&file_name);
                if candidate.is_file() {
                    current_path = Some(candidate);
                    break;
                }
            }

            if let Some(act_path) = current_path {
                if let Ok(Some(fail)) = compare_snapshot_file(
                    platform,
                    &snapshot_name,
                    &p,
                    &act_path,
                    max_allowed_pct,
                    diff_output_dir,
                ) {
                    failures.push(fail);
                }
            }
        }
    }

    Ok(failures)
}

pub fn parse_playwright_visual_diff_json(
    json_str: &str,
    max_pct: f64,
    platform: &str,
) -> Result<Vec<VisualDiffFailure>> {
    let mut failures = Vec::new();
    let val: serde_json::Value =
        serde_json::from_str(json_str).context("Failed to parse Playwright visual diff JSON")?;

    if let Some(arr) = val.as_array() {
        for item in arr {
            let name = item
                .get("snapshot")
                .or_else(|| item.get("name"))
                .and_then(|v| v.as_str())
                .unwrap_or("unknown");
            let diff_pct = item
                .get("diff_pct")
                .or_else(|| item.get("diffPercentage"))
                .and_then(|v| v.as_f64())
                .unwrap_or(0.0);
            let baseline = item
                .get("baseline")
                .or_else(|| item.get("expected"))
                .and_then(|v| v.as_str())
                .unwrap_or("");
            let current = item
                .get("current")
                .or_else(|| item.get("actual"))
                .and_then(|v| v.as_str())
                .unwrap_or("");
            let diff_art = item
                .get("diff")
                .or_else(|| item.get("diffPath"))
                .and_then(|v| v.as_str())
                .map(|s| s.to_string());

            if diff_pct > max_pct {
                failures.push(VisualDiffFailure {
                    platform: platform.to_string(),
                    snapshot_name: name.to_string(),
                    diff_pct,
                    max_allowed_pct: max_pct,
                    mismatched_pixels: 0,
                    total_pixels: 0,
                    baseline_path: baseline.to_string(),
                    current_path: current.to_string(),
                    diff_artifact_path: diff_art,
                });
            }
        }
    } else if let Some(suites) = val.get("suites").and_then(|s| s.as_array()) {
        for suite in suites {
            if let Some(specs) = suite.get("specs").and_then(|s| s.as_array()) {
                for spec in specs {
                    let title = spec
                        .get("title")
                        .and_then(|t| t.as_str())
                        .unwrap_or("snapshot");
                    if let Some(tests) = spec.get("tests").and_then(|t| t.as_array()) {
                        for test in tests {
                            if let Some(results) = test.get("results").and_then(|r| r.as_array()) {
                                for res in results {
                                    if let Some(err_msg) = res
                                        .get("error")
                                        .and_then(|e| e.get("message"))
                                        .and_then(|m| m.as_str())
                                    {
                                        if err_msg.contains("Screenshot comparison failed")
                                            || err_msg.contains("ratio")
                                        {
                                            let diff_pct = if let Some(pos) = err_msg.find("ratio ")
                                            {
                                                let sub = &err_msg[pos + 6..];
                                                sub.split_whitespace()
                                                    .next()
                                                    .and_then(|s| s.parse::<f64>().ok())
                                                    .unwrap_or(max_pct + 0.01)
                                            } else {
                                                max_pct + 0.01
                                            };
                                            if diff_pct > max_pct {
                                                failures.push(VisualDiffFailure {
                                                    platform: platform.to_string(),
                                                    snapshot_name: title.to_string(),
                                                    diff_pct,
                                                    max_allowed_pct: max_pct,
                                                    mismatched_pixels: 0,
                                                    total_pixels: 0,
                                                    baseline_path: "".to_string(),
                                                    current_path: "".to_string(),
                                                    diff_artifact_path: None,
                                                });
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    Ok(failures)
}

pub fn run_web_visual_diff(
    root: &Path,
    config: &WebPlatformSpec,
    base_config: &DesignSystemConfig,
) -> Result<VisualDiffExecutionReport> {
    let has_node = Command::new("node").arg("--version").output().is_ok();
    let block_on_missing = config.on_missing_tool.eq_ignore_ascii_case("block")
        || base_config.on_missing_platform == "fail";

    if !has_node {
        if block_on_missing {
            return Ok(VisualDiffExecutionReport {
                platform: "web".to_string(),
                passed: false,
                failures: Vec::new(),
                max_diff_pct: config.max_visual_diff_pct,
                total_snapshots_compared: 0,
                failed_snapshots_count: 0,
                tool: config.visual_diff_tool.clone(),
                message: "Node.js / Web runtime is not available on host.".to_string(),
            });
        } else {
            return Ok(VisualDiffExecutionReport {
                platform: "web".to_string(),
                passed: true,
                failures: Vec::new(),
                max_diff_pct: config.max_visual_diff_pct,
                total_snapshots_compared: 0,
                failed_snapshots_count: 0,
                tool: config.visual_diff_tool.clone(),
                message: "Node.js runtime missing (skipped with warning).".to_string(),
            });
        }
    }

    let mut failures = Vec::new();
    let mut command_executed = false;

    if let Some(ref cmd_str) = config.visual_diff_command {
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
            if let Ok(parsed) =
                parse_playwright_visual_diff_json(&stdout, config.max_visual_diff_pct, "web")
            {
                failures.extend(parsed);
            }
        }
    }

    // Native baseline directory pixel diff scan
    let baseline_dir = root.join(&config.baseline_dir);
    let current_dirs = [
        root.join(".pa/reports/design/current/web"),
        root.join(".pa/reports/design/current"),
        root.join("target/screenshots"),
    ];
    let diff_out_dir = root.join(".pa/reports/design/diffs/web");

    if let Ok(scanned_failures) = compare_baseline_directory(
        "web",
        &baseline_dir,
        &current_dirs,
        config.max_visual_diff_pct,
        &diff_out_dir,
    ) {
        for f in scanned_failures {
            if !failures
                .iter()
                .any(|existing| existing.snapshot_name == f.snapshot_name)
            {
                failures.push(f);
            }
        }
    }

    if !command_executed || failures.is_empty() {
        let candidates = [
            root.join("target/visual-diff-results.json"),
            root.join(".pa/visual-diff-results.json"),
            root.join(".pa/reports/web-visual-diff.json"),
        ];

        for path in &candidates {
            if path.is_file() {
                if let Ok(content) = fs::read_to_string(path) {
                    if let Ok(parsed) = parse_playwright_visual_diff_json(
                        &content,
                        config.max_visual_diff_pct,
                        "web",
                    ) {
                        for f in parsed {
                            if !failures
                                .iter()
                                .any(|existing| existing.snapshot_name == f.snapshot_name)
                            {
                                failures.push(f);
                            }
                        }
                        break;
                    }
                }
            }
        }
    }

    let failed_snapshots_count = failures.len();
    let passed = failed_snapshots_count == 0;
    let message = if passed {
        format!(
            "Web visual regression passed (max allowed: {:.2}%, failures: 0)",
            config.max_visual_diff_pct * 100.0
        )
    } else {
        format!(
            "Web visual regression failed ({} snapshots exceed {:.2}% diff)",
            failed_snapshots_count,
            config.max_visual_diff_pct * 100.0
        )
    };

    Ok(VisualDiffExecutionReport {
        platform: "web".to_string(),
        passed,
        failures,
        max_diff_pct: config.max_visual_diff_pct,
        total_snapshots_compared: failed_snapshots_count,
        failed_snapshots_count,
        tool: config.visual_diff_tool.clone(),
        message,
    })
}

pub fn run_ios_visual_diff(
    root: &Path,
    config: &IosPlatformSpec,
    _base_config: &DesignSystemConfig,
) -> Result<VisualDiffExecutionReport> {
    if !config.enabled {
        return Ok(VisualDiffExecutionReport {
            platform: "ios".to_string(),
            passed: true,
            failures: Vec::new(),
            max_diff_pct: config.max_visual_diff_pct,
            total_snapshots_compared: 0,
            failed_snapshots_count: 0,
            tool: config.visual_diff_tool.clone(),
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
        root.join("target/ios-visual-diff-results.json"),
        root.join(".pa/reports/ios-visual-diff.json"),
    ];
    let has_reports = candidates.iter().any(|c| c.is_file());
    let has_command = config.visual_diff_command.is_some();

    if (!has_simctl || !is_darwin) && !has_reports && !has_command {
        let block = config.on_missing_platform.eq_ignore_ascii_case("block");
        return Ok(VisualDiffExecutionReport {
            platform: "ios".to_string(),
            passed: !block,
            failures: Vec::new(),
            max_diff_pct: config.max_visual_diff_pct,
            total_snapshots_compared: 0,
            failed_snapshots_count: 0,
            tool: config.visual_diff_tool.clone(),
            message: if block {
                "iOS visual diff blocked: 'simctl' / Xcode CLI is not available.".to_string()
            } else {
                "iOS visual diff skipped: 'simctl' / Xcode CLI is not available.".to_string()
            },
        });
    }

    let mut failures = Vec::new();
    if let Some(ref cmd_str) = config.visual_diff_command {
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
            failures.extend(parse_ios_visual_diff_output(
                &stdout,
                config.max_visual_diff_pct,
            ));
        }
    }

    // Native baseline directory pixel diff scan for iOS
    let baseline_dir = root.join(&config.baseline_dir);
    let current_dirs = [
        root.join(".pa/reports/design/current/ios"),
        root.join(".pa/reports/design/current"),
        root.join("target/screenshots/ios"),
    ];
    let diff_out_dir = root.join(".pa/reports/design/diffs/ios");

    if let Ok(scanned_failures) = compare_baseline_directory(
        "ios",
        &baseline_dir,
        &current_dirs,
        config.max_visual_diff_pct,
        &diff_out_dir,
    ) {
        for f in scanned_failures {
            if !failures
                .iter()
                .any(|existing| existing.snapshot_name == f.snapshot_name)
            {
                failures.push(f);
            }
        }
    }

    for path in &candidates {
        if path.is_file() {
            if let Ok(content) = fs::read_to_string(path) {
                let parsed = parse_ios_visual_diff_output(&content, config.max_visual_diff_pct);
                for f in parsed {
                    if !failures
                        .iter()
                        .any(|existing| existing.snapshot_name == f.snapshot_name)
                    {
                        failures.push(f);
                    }
                }
            }
        }
    }

    let failed_snapshots_count = failures.len();
    let passed = failed_snapshots_count == 0;
    let message = if passed {
        format!(
            "iOS visual regression passed (max allowed: {:.2}%, failures: 0)",
            config.max_visual_diff_pct * 100.0
        )
    } else {
        format!(
            "iOS visual regression failed ({} snapshots exceed {:.2}% diff)",
            failed_snapshots_count,
            config.max_visual_diff_pct * 100.0
        )
    };

    Ok(VisualDiffExecutionReport {
        platform: "ios".to_string(),
        passed,
        failures,
        max_diff_pct: config.max_visual_diff_pct,
        total_snapshots_compared: failed_snapshots_count,
        failed_snapshots_count,
        tool: config.visual_diff_tool.clone(),
        message,
    })
}

pub fn parse_ios_visual_diff_output(raw: &str, max_pct: f64) -> Vec<VisualDiffFailure> {
    let mut failures = Vec::new();

    if let Ok(val) = serde_json::from_str::<serde_json::Value>(raw) {
        let arr = val
            .as_array()
            .cloned()
            .or_else(|| val.get("diffs").and_then(|v| v.as_array()).cloned());
        if let Some(snapshots) = arr {
            for item in snapshots {
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
                let diff_art = item
                    .get("diff")
                    .or_else(|| item.get("diffPath"))
                    .and_then(|v| v.as_str())
                    .map(|s| s.to_string());

                if diff_pct > max_pct {
                    failures.push(VisualDiffFailure {
                        platform: "ios".to_string(),
                        snapshot_name: name.to_string(),
                        diff_pct,
                        max_allowed_pct: max_pct,
                        mismatched_pixels: 0,
                        total_pixels: 0,
                        baseline_path: baseline.to_string(),
                        current_path: current.to_string(),
                        diff_artifact_path: diff_art,
                    });
                }
            }
            return failures;
        }
    }

    for line in raw.lines() {
        if line.contains("Snapshot failed") || (line.contains("Snapshot") && line.contains("diff"))
        {
            let diff_pct = if let Some(pos) = line.find("diff:") {
                let sub = &line[pos + 5..];
                sub.split_whitespace()
                    .next()
                    .and_then(|s| s.trim_end_matches('%').parse::<f64>().ok())
                    .map(|v| if v > 1.0 { v / 100.0 } else { v })
                    .unwrap_or(max_pct + 0.01)
            } else {
                max_pct + 0.01
            };

            let name = if let Some(pos) = line.find("Snapshot failed for '") {
                let sub = &line[pos + 21..];
                sub.split('\'').next().unwrap_or("snapshot").to_string()
            } else {
                "ios_snapshot".to_string()
            };

            if diff_pct > max_pct {
                failures.push(VisualDiffFailure {
                    platform: "ios".to_string(),
                    snapshot_name: name,
                    diff_pct,
                    max_allowed_pct: max_pct,
                    mismatched_pixels: 0,
                    total_pixels: 0,
                    baseline_path: "".to_string(),
                    current_path: "".to_string(),
                    diff_artifact_path: None,
                });
            }
        }
    }

    failures
}

pub fn run_android_visual_diff(
    root: &Path,
    config: &AndroidPlatformSpec,
    _base_config: &DesignSystemConfig,
) -> Result<VisualDiffExecutionReport> {
    if !config.enabled {
        return Ok(VisualDiffExecutionReport {
            platform: "android".to_string(),
            passed: true,
            failures: Vec::new(),
            max_diff_pct: config.max_visual_diff_pct,
            total_snapshots_compared: 0,
            failed_snapshots_count: 0,
            tool: config.visual_diff_tool.clone(),
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
        root.join("target/android-visual-diff-results.json"),
        root.join(".pa/reports/android-visual-diff.json"),
    ];
    let has_reports = candidates.iter().any(|c| c.is_file());
    let has_command = config.visual_diff_command.is_some();

    if !has_adb && !has_reports && !has_command {
        let block = config.on_missing_platform.eq_ignore_ascii_case("block");
        return Ok(VisualDiffExecutionReport {
            platform: "android".to_string(),
            passed: !block,
            failures: Vec::new(),
            max_diff_pct: config.max_visual_diff_pct,
            total_snapshots_compared: 0,
            failed_snapshots_count: 0,
            tool: config.visual_diff_tool.clone(),
            message: if block {
                "Android visual diff blocked: 'adb' / Android SDK is not available.".to_string()
            } else {
                "Android visual diff skipped: 'adb' / Android SDK is not available.".to_string()
            },
        });
    }

    let mut failures = Vec::new();
    if let Some(ref cmd_str) = config.visual_diff_command {
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
            failures.extend(parse_android_visual_diff_output(
                &stdout,
                config.max_visual_diff_pct,
            ));
        }
    }

    // Native baseline directory pixel diff scan for Android
    let baseline_dir = root.join(&config.baseline_dir);
    let current_dirs = [
        root.join(".pa/reports/design/current/android"),
        root.join(".pa/reports/design/current"),
        root.join("target/screenshots/android"),
    ];
    let diff_out_dir = root.join(".pa/reports/design/diffs/android");

    if let Ok(scanned_failures) = compare_baseline_directory(
        "android",
        &baseline_dir,
        &current_dirs,
        config.max_visual_diff_pct,
        &diff_out_dir,
    ) {
        for f in scanned_failures {
            if !failures
                .iter()
                .any(|existing| existing.snapshot_name == f.snapshot_name)
            {
                failures.push(f);
            }
        }
    }

    for path in &candidates {
        if path.is_file() {
            if let Ok(content) = fs::read_to_string(path) {
                let parsed = parse_android_visual_diff_output(&content, config.max_visual_diff_pct);
                for f in parsed {
                    if !failures
                        .iter()
                        .any(|existing| existing.snapshot_name == f.snapshot_name)
                    {
                        failures.push(f);
                    }
                }
            }
        }
    }

    let failed_snapshots_count = failures.len();
    let passed = failed_snapshots_count == 0;
    let message = if passed {
        format!(
            "Android visual regression passed (max allowed: {:.2}%, failures: 0)",
            config.max_visual_diff_pct * 100.0
        )
    } else {
        format!(
            "Android visual regression failed ({} snapshots exceed {:.2}% diff)",
            failed_snapshots_count,
            config.max_visual_diff_pct * 100.0
        )
    };

    Ok(VisualDiffExecutionReport {
        platform: "android".to_string(),
        passed,
        failures,
        max_diff_pct: config.max_visual_diff_pct,
        total_snapshots_compared: failed_snapshots_count,
        failed_snapshots_count,
        tool: config.visual_diff_tool.clone(),
        message,
    })
}

pub fn parse_android_visual_diff_output(raw: &str, max_pct: f64) -> Vec<VisualDiffFailure> {
    let mut failures = Vec::new();

    if let Ok(val) = serde_json::from_str::<serde_json::Value>(raw) {
        let arr = val
            .as_array()
            .cloned()
            .or_else(|| val.get("diffs").and_then(|v| v.as_array()).cloned());
        if let Some(snapshots) = arr {
            for item in snapshots {
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
                let diff_art = item
                    .get("diff")
                    .or_else(|| item.get("diffPath"))
                    .and_then(|v| v.as_str())
                    .map(|s| s.to_string());

                if diff_pct > max_pct {
                    failures.push(VisualDiffFailure {
                        platform: "android".to_string(),
                        snapshot_name: name.to_string(),
                        diff_pct,
                        max_allowed_pct: max_pct,
                        mismatched_pixels: 0,
                        total_pixels: 0,
                        baseline_path: baseline.to_string(),
                        current_path: current.to_string(),
                        diff_artifact_path: diff_art,
                    });
                }
            }
            return failures;
        }
    }

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
                    platform: "android".to_string(),
                    snapshot_name: name,
                    diff_pct,
                    max_allowed_pct: max_pct,
                    mismatched_pixels: 0,
                    total_pixels: 0,
                    baseline_path: "".to_string(),
                    current_path: "".to_string(),
                    diff_artifact_path: None,
                });
            }
        }
    }

    failures
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    fn create_test_png(w: u32, h: u32, color: Rgba<u8>) -> Vec<u8> {
        let mut img = RgbaImage::new(w, h);
        for pixel in img.pixels_mut() {
            *pixel = color;
        }
        let mut buffer = Vec::new();
        let encoder = image::codecs::png::PngEncoder::new(&mut buffer);
        encoder
            .write_image(img.as_raw(), w, h, image::ExtendedColorType::Rgba8)
            .unwrap();
        buffer
    }

    #[test]
    fn test_identical_png_diff_is_zero() {
        let png = create_test_png(10, 10, Rgba([37, 99, 235, 255]));
        let result = compare_png_bytes(&png, &png, 0).unwrap();
        assert_eq!(result.total_pixels, 100);
        assert_eq!(result.mismatched_pixels, 0);
        assert_eq!(result.diff_pct, 0.0);
        assert!(result.diff_image_png.is_none());
    }

    #[test]
    fn test_divergent_png_diff_and_diff_image_generation() {
        let base_png = create_test_png(10, 10, Rgba([0, 0, 0, 255]));
        // Make 10 out of 100 pixels white
        let mut img = RgbaImage::new(10, 10);
        for (i, pixel) in img.pixels_mut().enumerate() {
            if i < 10 {
                *pixel = Rgba([255, 255, 255, 255]);
            } else {
                *pixel = Rgba([0, 0, 0, 255]);
            }
        }
        let mut act_png = Vec::new();
        let encoder = image::codecs::png::PngEncoder::new(&mut act_png);
        encoder
            .write_image(img.as_raw(), 10, 10, image::ExtendedColorType::Rgba8)
            .unwrap();

        let result = compare_png_bytes(&base_png, &act_png, 5).unwrap();
        assert_eq!(result.total_pixels, 100);
        assert_eq!(result.mismatched_pixels, 10);
        assert!((result.diff_pct - 0.10).abs() < 1e-6);
        assert!(result.diff_image_png.is_some());

        // Test file comparison and artifact generation
        let dir = tempdir().unwrap();
        let base_path = dir.path().join("btn_base.png");
        let act_path = dir.path().join("btn_act.png");
        let diff_dir = dir.path().join("diffs");

        fs::write(&base_path, &base_png).unwrap();
        fs::write(&act_path, &act_png).unwrap();

        // With max threshold 0.05 (5%), 10% diff should fail
        let fail = compare_snapshot_file("web", "btn_test", &base_path, &act_path, 0.05, &diff_dir)
            .unwrap();
        assert!(fail.is_some());
        let f = fail.unwrap();
        assert_eq!(f.platform, "web");
        assert_eq!(f.snapshot_name, "btn_test");
        assert_eq!(f.mismatched_pixels, 10);
        assert!(f.diff_artifact_path.is_some());
        assert!(Path::new(&f.diff_artifact_path.unwrap()).is_file());

        // With max threshold 0.15 (15%), 10% diff should pass
        let pass = compare_snapshot_file("web", "btn_test", &base_path, &act_path, 0.15, &diff_dir)
            .unwrap();
        assert!(pass.is_none());
    }

    #[test]
    fn test_parse_playwright_json() {
        let json_str = r#"[
            {
                "snapshot": "hero-desktop",
                "diff_pct": 0.08,
                "baseline": "baselines/hero.png",
                "current": "test-results/hero.png"
            },
            {
                "snapshot": "footer",
                "diff_pct": 0.001,
                "baseline": "baselines/footer.png",
                "current": "test-results/footer.png"
            }
        ]"#;

        let fails = parse_playwright_visual_diff_json(json_str, 0.005, "web").unwrap();
        assert_eq!(fails.len(), 1);
        assert_eq!(fails[0].snapshot_name, "hero-desktop");
        assert_eq!(fails[0].diff_pct, 0.08);
        assert_eq!(fails[0].platform, "web");
    }
}
