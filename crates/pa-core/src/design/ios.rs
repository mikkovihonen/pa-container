use anyhow::Result;
use std::path::Path;

use crate::schema::{DesignSystemConfig, IosPlatformSpec};

pub use super::a11y::parse_ios_a11y_output;
pub use super::visual_diff::parse_ios_visual_diff_output;
use super::{A11yViolation, PlatformGateResult, VisualDiffFailure};

pub struct IosEvaluationResult {
    pub gate_result: PlatformGateResult,
    pub a11y_violations: Vec<A11yViolation>,
    pub visual_diff_failures: Vec<VisualDiffFailure>,
}

pub fn evaluate_ios_platform(
    root: &Path,
    config: &IosPlatformSpec,
    base_config: &DesignSystemConfig,
) -> Result<IosEvaluationResult> {
    let a11y_res = super::a11y::run_ios_a11y(root, config, base_config)?;
    let visual_res = super::visual_diff::run_ios_visual_diff(root, config, base_config)?;

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

    Ok(IosEvaluationResult {
        gate_result: PlatformGateResult {
            platform: "ios".to_string(),
            status,
            message: format!(
                "iOS platform active (runner: {}, a11y: {}, visual: {})",
                config.runner, config.a11y_engine, config.visual_diff_tool
            ),
            details,
        },
        a11y_violations: a11y_res.violations,
        visual_diff_failures: visual_res.failures,
    })
}
