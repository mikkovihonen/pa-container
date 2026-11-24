use anyhow::Result;
use std::path::Path;

use crate::schema::{AndroidPlatformSpec, DesignSystemConfig};

pub use super::a11y::parse_android_a11y_output;
pub use super::visual_diff::parse_android_visual_diff_output;
use super::{A11yViolation, PlatformGateResult, VisualDiffFailure};

pub struct AndroidEvaluationResult {
    pub gate_result: PlatformGateResult,
    pub a11y_violations: Vec<A11yViolation>,
    pub visual_diff_failures: Vec<VisualDiffFailure>,
}

pub fn evaluate_android_platform(
    root: &Path,
    config: &AndroidPlatformSpec,
    base_config: &DesignSystemConfig,
) -> Result<AndroidEvaluationResult> {
    let a11y_res = super::a11y::run_android_a11y(root, config, base_config)?;
    let visual_res = super::visual_diff::run_android_visual_diff(root, config, base_config)?;

    let is_skipped = !config.enabled
        || a11y_res.message.contains("skipped")
        || visual_res.message.contains("skipped");
    let passed = a11y_res.passed && visual_res.passed;
    let status = if !passed {
        "failed".to_string()
    } else if is_skipped {
        "skipped".to_string()
    } else {
        "passed".to_string()
    };

    let details = vec![a11y_res.message, visual_res.message];

    Ok(AndroidEvaluationResult {
        gate_result: PlatformGateResult {
            platform: "android".to_string(),
            status,
            message: format!(
                "Android platform active (runner: {}, a11y: {}, visual: {})",
                config.runner, config.a11y_engine, config.visual_diff_tool
            ),
            details,
        },
        a11y_violations: a11y_res.violations,
        visual_diff_failures: visual_res.failures,
    })
}
