pub mod android;
pub mod compiler;
pub mod drift;
pub mod ios;

use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fs;
use std::path::Path;
use std::process::Command;

use crate::schema::DesignSystemConfig;

pub use android::{
    evaluate_android_platform, parse_android_a11y_output, parse_android_visual_diff_output,
};
pub use compiler::{
    check_tokens_freshness, check_tool_availability, compile_design_tokens, compute_file_digest,
    TokenCompileReport, TokenFreshnessReport,
};
pub use drift::{find_hardcoded_hex, scan_workspace_for_drift, DriftScanResult};
pub use ios::{evaluate_ios_platform, parse_ios_a11y_output, parse_ios_visual_diff_output};

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct DesignToken {
    pub name: String,
    pub token_type: String,
    pub value: String,
    pub description: Option<String>,
    pub source: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default, PartialEq)]
pub struct TokenCatalog {
    pub tokens: HashMap<String, DesignToken>,
}

impl TokenCatalog {
    pub fn empty() -> Self {
        Self {
            tokens: HashMap::new(),
        }
    }

    pub fn from_json_str(content: &str, source: &str) -> Result<Self> {
        let val: serde_json::Value =
            serde_json::from_str(content).context("Failed to parse DTCG token JSON")?;
        let mut tokens = HashMap::new();
        Self::traverse_dtcg("", &val, source, &mut tokens);
        Ok(Self { tokens })
    }

    pub fn from_file(path: &Path) -> Result<Self> {
        let content = fs::read_to_string(path)
            .with_context(|| format!("Failed to read tokens file at {}", path.display()))?;
        let source = path.display().to_string();
        Self::from_json_str(&content, &source)
    }

    pub fn from_dir(dir: &Path) -> Result<Self> {
        let mut merged = HashMap::new();
        if dir.is_dir() {
            for entry in fs::read_dir(dir)?.filter_map(|e| e.ok()) {
                let p = entry.path();
                if p.extension().and_then(|e| e.to_str()) == Some("json") {
                    if let Ok(catalog) = Self::from_file(&p) {
                        merged.extend(catalog.tokens);
                    }
                }
            }
        }
        Ok(Self { tokens: merged })
    }

    fn traverse_dtcg(
        prefix: &str,
        val: &serde_json::Value,
        source: &str,
        tokens: &mut HashMap<String, DesignToken>,
    ) {
        if let Some(obj) = val.as_object() {
            if let Some(v_field) = obj.get("$value") {
                let token_type = obj
                    .get("$type")
                    .and_then(|t| t.as_str())
                    .unwrap_or_else(|| {
                        if prefix.starts_with("color") {
                            "color"
                        } else if prefix.starts_with("spacing") {
                            "dimension"
                        } else {
                            "string"
                        }
                    })
                    .to_string();

                let desc = obj
                    .get("$description")
                    .and_then(|d| d.as_str())
                    .map(|s| s.to_string());

                let value_str = match v_field {
                    serde_json::Value::String(s) => s.clone(),
                    serde_json::Value::Number(n) => n.to_string(),
                    serde_json::Value::Bool(b) => b.to_string(),
                    other => other.to_string(),
                };

                tokens.insert(
                    prefix.to_string(),
                    DesignToken {
                        name: prefix.to_string(),
                        token_type,
                        value: value_str,
                        description: desc,
                        source: source.to_string(),
                    },
                );
                return;
            }

            for (k, v) in obj {
                if k.starts_with('$') {
                    continue;
                }
                let next_prefix = if prefix.is_empty() {
                    k.clone()
                } else {
                    format!("{}.{}", prefix, k)
                };
                Self::traverse_dtcg(&next_prefix, v, source, tokens);
            }
        }
    }

    pub fn get(&self, name: &str) -> Option<&DesignToken> {
        self.tokens.get(name)
    }

    pub fn resolve_value(&self, raw: &str) -> String {
        if raw.starts_with('{') && raw.ends_with('}') {
            let alias = &raw[1..raw.len() - 1];
            if let Some(tok) = self.get(alias) {
                return self.resolve_value(&tok.value);
            }
        }
        raw.to_string()
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Default)]
pub struct WebContractBinding {
    #[serde(default)]
    pub component: String,
    #[serde(default)]
    pub catalog_entry: String,
    #[serde(default)]
    pub a11y_target: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Default)]
pub struct IosContractBinding {
    #[serde(default)]
    pub component: String,
    #[serde(default)]
    pub catalog_entry: String,
    #[serde(default)]
    pub a11y_target: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Default)]
pub struct AndroidContractBinding {
    #[serde(default)]
    pub component: String,
    #[serde(default)]
    pub catalog_entry: String,
    #[serde(default)]
    pub a11y_target: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ComponentContract {
    pub name: String,
    #[serde(default)]
    pub description: Option<String>,
    #[serde(default)]
    pub platforms: Vec<String>,
    #[serde(default)]
    pub tokens: Vec<String>,
    #[serde(default)]
    pub web: Option<WebContractBinding>,
    #[serde(default)]
    pub ios: Option<IosContractBinding>,
    #[serde(default)]
    pub android: Option<AndroidContractBinding>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct DesignSystemStore {
    pub provider: String,
    pub catalog: TokenCatalog,
    pub contracts: HashMap<String, ComponentContract>,
}

impl DesignSystemStore {
    pub fn load(root: &Path, config: &DesignSystemConfig) -> Result<Self> {
        match config.provider.to_lowercase().as_str() {
            "none" => Ok(Self {
                provider: "none".to_string(),
                catalog: TokenCatalog::empty(),
                contracts: HashMap::new(),
            }),
            "git_only" => Self::load_git_only(root, &config.tokens_path, &config.contracts_path),
            "penpot" => {
                let mut store =
                    Self::load_git_only(root, &config.tokens_path, &config.contracts_path)?;
                store.provider = "penpot".to_string();
                Ok(store)
            }
            "figma" => {
                let mut store =
                    Self::load_git_only(root, &config.tokens_path, &config.contracts_path)?;
                store.provider = "figma".to_string();
                Ok(store)
            }
            other => Self::load_git_only(root, &config.tokens_path, &config.contracts_path).map(
                |mut s| {
                    s.provider = other.to_string();
                    s
                },
            ),
        }
    }

    fn load_git_only(root: &Path, tokens_path: &Path, contracts_path: &Path) -> Result<Self> {
        let abs_tokens = root.join(tokens_path);
        let catalog = if abs_tokens.is_file() {
            TokenCatalog::from_file(&abs_tokens)?
        } else if abs_tokens.is_dir() {
            TokenCatalog::from_dir(&abs_tokens)?
        } else {
            TokenCatalog::empty()
        };

        let mut contracts = HashMap::new();
        let abs_contracts = root.join(contracts_path);
        if abs_contracts.is_dir() {
            for entry in fs::read_dir(&abs_contracts)?.filter_map(|e| e.ok()) {
                let path = entry.path();
                let ext = path.extension().and_then(|e| e.to_str()).unwrap_or("");
                if ext == "toml" {
                    if let Ok(content) = fs::read_to_string(&path) {
                        if let Ok(contract) = toml::from_str::<ComponentContract>(&content) {
                            contracts.insert(contract.name.clone(), contract);
                        }
                    }
                } else if ext == "json" {
                    if let Ok(content) = fs::read_to_string(&path) {
                        if let Ok(contract) = serde_json::from_str::<ComponentContract>(&content) {
                            contracts.insert(contract.name.clone(), contract);
                        }
                    }
                }
            }
        }

        Ok(Self {
            provider: "git_only".to_string(),
            catalog,
            contracts,
        })
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct DesignLintViolation {
    pub file: String,
    pub line: usize,
    pub rule: String,
    pub message: String,
    pub severity: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct PlatformGateResult {
    pub platform: String,
    pub status: String, // "passed", "failed", "skipped"
    pub message: String,
    pub details: Vec<String>,
}

pub type PlatformDesignResult = PlatformGateResult;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct A11yViolation {
    pub id: String,
    pub impact: String,
    pub description: String,
    pub help_url: Option<String>,
    pub nodes_count: usize,
    pub target: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct VisualDiffFailure {
    pub snapshot_name: String,
    pub diff_pct: f64,
    pub max_allowed_pct: f64,
    pub baseline_path: String,
    pub current_path: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct DesignGateReport {
    pub provider: String,
    pub is_compliant: bool,
    pub total_tokens: usize,
    pub total_contracts: usize,
    #[serde(default)]
    pub needs_design_review: bool,
    #[serde(default)]
    pub new_components: Vec<String>,
    pub platform_results: HashMap<String, PlatformGateResult>,
    pub violations: Vec<DesignLintViolation>,
    #[serde(default)]
    pub a11y_violations: Vec<A11yViolation>,
    #[serde(default)]
    pub visual_diff_failures: Vec<VisualDiffFailure>,
}

impl DesignGateReport {
    pub fn empty(provider: &str) -> Self {
        Self {
            provider: provider.to_string(),
            is_compliant: true,
            total_tokens: 0,
            total_contracts: 0,
            needs_design_review: false,
            new_components: Vec::new(),
            platform_results: HashMap::new(),
            violations: Vec::new(),
            a11y_violations: Vec::new(),
            visual_diff_failures: Vec::new(),
        }
    }
}

pub fn parse_axe_violations_json(json_str: &str, wcag_level: &str) -> Result<Vec<A11yViolation>> {
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
                .any(|t| t.contains("wcag2a") || t.contains("wcag21a") || t.contains("wcag22a")),
            "AA" => tags.iter().any(|t| {
                t.contains("wcag2a")
                    || t.contains("wcag2aa")
                    || t.contains("wcag21a")
                    || t.contains("wcag21aa")
                    || t.contains("wcag22aa")
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

pub fn parse_playwright_visual_diff_json(
    json_str: &str,
    max_pct: f64,
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
                                                    snapshot_name: title.to_string(),
                                                    diff_pct,
                                                    max_allowed_pct: max_pct,
                                                    baseline_path: "".to_string(),
                                                    current_path: "".to_string(),
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

pub fn evaluate_design_gate(root: &Path, config: &DesignSystemConfig) -> Result<DesignGateReport> {
    if config.provider == "none" {
        return Ok(DesignGateReport::empty("none"));
    }

    let store = DesignSystemStore::load(root, config)?;
    let mut violations = Vec::new();
    let mut a11y_violations = Vec::new();
    let mut visual_diff_failures = Vec::new();
    let mut platform_results = HashMap::new();
    let mut is_compliant = true;

    // 1. Check prerequisite toolchains and execute quality runners for enabled platforms
    for platform in &config.platforms {
        match platform.as_str() {
            "web" => {
                let has_node = Command::new("node").arg("--version").output().is_ok();
                let block_on_missing = config.web.on_missing_tool.eq_ignore_ascii_case("block")
                    || config.on_missing_platform == "fail";

                if !has_node {
                    if block_on_missing {
                        is_compliant = false;
                        platform_results.insert(
                            "web".to_string(),
                            PlatformGateResult {
                                platform: "web".to_string(),
                                status: "failed".to_string(),
                                message: "Node.js / Web runtime is not available on host.".to_string(),
                                details: vec![
                                    "Please install Node.js or disable 'web' in factory.toml platforms."
                                        .to_string(),
                                ],
                            },
                        );
                    } else {
                        platform_results.insert(
                            "web".to_string(),
                            PlatformGateResult {
                                platform: "web".to_string(),
                                status: "skipped".to_string(),
                                message: "Node.js runtime missing (skipped with warning)."
                                    .to_string(),
                                details: Vec::new(),
                            },
                        );
                    }
                } else {
                    let mut web_details = Vec::new();
                    let mut web_passed = true;

                    // 1. Accessibility (axe-core)
                    let mut a11y_found_any = false;
                    if let Some(ref cmd_str) = config.web.a11y_command {
                        let out = Command::new("sh")
                            .arg("-c")
                            .arg(cmd_str)
                            .current_dir(root)
                            .output();

                        if let Ok(o) = out {
                            let stdout = String::from_utf8_lossy(&o.stdout);
                            if let Ok(vulns) =
                                parse_axe_violations_json(&stdout, &config.web.wcag_level)
                            {
                                a11y_found_any = true;
                                for v in vulns {
                                    if v.impact == "serious" || v.impact == "critical" {
                                        web_passed = false;
                                        is_compliant = false;
                                        violations.push(DesignLintViolation {
                                            file: v
                                                .target
                                                .clone()
                                                .unwrap_or_else(|| "web".to_string()),
                                            line: 1,
                                            rule: "a11y_wcag_violation".to_string(),
                                            message: format!(
                                                "[axe-core] WCAG {} {} violation in '{}': {}",
                                                config.web.wcag_level,
                                                v.impact,
                                                v.id,
                                                v.description
                                            ),
                                            severity: "error".to_string(),
                                        });
                                    }
                                    a11y_violations.push(v);
                                }
                            }
                        }
                    }

                    let a11y_file = root.join("target/a11y-results.json");
                    let a11y_file_pa = root.join(".pa/a11y-results.json");
                    let a11y_path = if a11y_file.is_file() {
                        Some(a11y_file)
                    } else if a11y_file_pa.is_file() {
                        Some(a11y_file_pa)
                    } else {
                        None
                    };

                    if !a11y_found_any {
                        if let Some(p) = a11y_path {
                            if let Ok(content) = fs::read_to_string(&p) {
                                if let Ok(vulns) =
                                    parse_axe_violations_json(&content, &config.web.wcag_level)
                                {
                                    for v in vulns {
                                        if v.impact == "serious" || v.impact == "critical" {
                                            web_passed = false;
                                            is_compliant = false;
                                            violations.push(DesignLintViolation {
                                                file: v
                                                    .target
                                                    .clone()
                                                    .unwrap_or_else(|| "web".to_string()),
                                                line: 1,
                                                rule: "a11y_wcag_violation".to_string(),
                                                message: format!(
                                                    "[axe-core] WCAG {} {} violation in '{}': {}",
                                                    config.web.wcag_level,
                                                    v.impact,
                                                    v.id,
                                                    v.description
                                                ),
                                                severity: "error".to_string(),
                                            });
                                        }
                                        a11y_violations.push(v);
                                    }
                                }
                            }
                        }
                    }

                    // 2. Visual Regression (Playwright)
                    let mut visual_found_any = false;
                    if let Some(ref cmd_str) = config.web.visual_diff_command {
                        let out = Command::new("sh")
                            .arg("-c")
                            .arg(cmd_str)
                            .current_dir(root)
                            .output();

                        if let Ok(o) = out {
                            let stdout = String::from_utf8_lossy(&o.stdout);
                            if let Ok(diffs) = parse_playwright_visual_diff_json(
                                &stdout,
                                config.web.max_visual_diff_pct,
                            ) {
                                visual_found_any = true;
                                for d in diffs {
                                    web_passed = false;
                                    is_compliant = false;
                                    violations.push(DesignLintViolation {
                                        file: d.snapshot_name.clone(),
                                        line: 1,
                                        rule: "visual_regression_violation".to_string(),
                                        message: format!(
                                            "[playwright visual diff] Snapshot '{}' diff {:.2}% exceeds max allowed {:.2}%",
                                            d.snapshot_name,
                                            d.diff_pct * 100.0,
                                            d.max_allowed_pct * 100.0
                                        ),
                                        severity: "error".to_string(),
                                    });
                                    visual_diff_failures.push(d);
                                }
                            }
                        }
                    }

                    let visual_file = root.join("target/visual-diff-results.json");
                    let visual_file_pa = root.join(".pa/visual-diff-results.json");
                    let visual_path = if visual_file.is_file() {
                        Some(visual_file)
                    } else if visual_file_pa.is_file() {
                        Some(visual_file_pa)
                    } else {
                        None
                    };

                    if !visual_found_any {
                        if let Some(p) = visual_path {
                            if let Ok(content) = fs::read_to_string(&p) {
                                if let Ok(diffs) = parse_playwright_visual_diff_json(
                                    &content,
                                    config.web.max_visual_diff_pct,
                                ) {
                                    for d in diffs {
                                        web_passed = false;
                                        is_compliant = false;
                                        violations.push(DesignLintViolation {
                                            file: d.snapshot_name.clone(),
                                            line: 1,
                                            rule: "visual_regression_violation".to_string(),
                                            message: format!(
                                                "[playwright visual diff] Snapshot '{}' diff {:.2}% exceeds max allowed {:.2}%",
                                                d.snapshot_name,
                                                d.diff_pct * 100.0,
                                                d.max_allowed_pct * 100.0
                                            ),
                                            severity: "error".to_string(),
                                        });
                                        visual_diff_failures.push(d);
                                    }
                                }
                            }
                        }
                    }

                    web_details.push(format!(
                        "Accessibility (engine: {}, wcag: {}, violations: {})",
                        config.web.a11y_engine,
                        config.web.wcag_level,
                        a11y_violations.len()
                    ));
                    web_details.push(format!(
                        "Visual Regression (tool: {}, max_diff: {:.1}%, failures: {})",
                        config.web.visual_diff_tool,
                        config.web.max_visual_diff_pct * 100.0,
                        visual_diff_failures.len()
                    ));

                    platform_results.insert(
                        "web".to_string(),
                        PlatformGateResult {
                            platform: "web".to_string(),
                            status: if web_passed {
                                "passed".to_string()
                            } else {
                                "failed".to_string()
                            },
                            message: format!(
                                "Web platform active (catalog: {}, a11y: {}, visual: {})",
                                config.web.catalog,
                                config.web.a11y_engine,
                                config.web.visual_regression
                            ),
                            details: web_details,
                        },
                    );
                }
            }
            "ios" => {
                let ios_res = evaluate_ios_platform(root, &config.ios, config)?;
                if ios_res.gate_result.status == "failed" {
                    is_compliant = false;
                }
                for v in &ios_res.a11y_violations {
                    if v.impact == "serious" || v.impact == "critical" {
                        violations.push(DesignLintViolation {
                            file: v.target.clone().unwrap_or_else(|| "ios".to_string()),
                            line: 1,
                            rule: "a11y_ios_violation".to_string(),
                            message: format!(
                                "[XCTest a11y] {} in target '{:?}'",
                                v.description, v.target
                            ),
                            severity: "error".to_string(),
                        });
                    }
                }
                for d in &ios_res.visual_diff_failures {
                    violations.push(DesignLintViolation {
                        file: d.snapshot_name.clone(),
                        line: 1,
                        rule: "visual_regression_ios".to_string(),
                        message: format!(
                            "[iOS visual diff] Snapshot '{}' diff {:.2}% exceeds max allowed {:.2}%",
                            d.snapshot_name, d.diff_pct * 100.0, d.max_allowed_pct * 100.0
                        ),
                        severity: "error".to_string(),
                    });
                }
                a11y_violations.extend(ios_res.a11y_violations);
                visual_diff_failures.extend(ios_res.visual_diff_failures);
                platform_results.insert("ios".to_string(), ios_res.gate_result);
            }
            "android" => {
                let android_res = evaluate_android_platform(root, &config.android, config)?;
                if android_res.gate_result.status == "failed" {
                    is_compliant = false;
                }
                for v in &android_res.a11y_violations {
                    if v.impact == "serious" || v.impact == "critical" {
                        violations.push(DesignLintViolation {
                            file: v.target.clone().unwrap_or_else(|| "android".to_string()),
                            line: 1,
                            rule: "a11y_android_violation".to_string(),
                            message: format!(
                                "[Android a11y] {} in target '{:?}'",
                                v.description, v.target
                            ),
                            severity: "error".to_string(),
                        });
                    }
                }
                for d in &android_res.visual_diff_failures {
                    violations.push(DesignLintViolation {
                        file: d.snapshot_name.clone(),
                        line: 1,
                        rule: "visual_regression_android".to_string(),
                        message: format!(
                            "[Android visual diff] Snapshot '{}' diff {:.2}% exceeds max allowed {:.2}%",
                            d.snapshot_name, d.diff_pct * 100.0, d.max_allowed_pct * 100.0
                        ),
                        severity: "error".to_string(),
                    });
                }
                a11y_violations.extend(android_res.a11y_violations);
                visual_diff_failures.extend(android_res.visual_diff_failures);
                platform_results.insert("android".to_string(), android_res.gate_result);
            }
            other => {
                platform_results.insert(
                    other.to_string(),
                    PlatformGateResult {
                        platform: other.to_string(),
                        status: "passed".to_string(),
                        message: "Custom platform configuration accepted".to_string(),
                        details: Vec::new(),
                    },
                );
            }
        }
    }

    // 2. AST Component Drift & Token Linting
    let drift_res =
        scan_workspace_for_drift(root, &config.drift, &store.contracts, &store.catalog)?;
    violations.extend(drift_res.violations);

    // 3. Verify Component Contract Token Linkage
    for (name, contract) in &store.contracts {
        for tok_name in &contract.tokens {
            if store.catalog.get(tok_name).is_none() {
                violations.push(DesignLintViolation {
                    file: format!("design/contracts/{}.toml", name.to_lowercase()),
                    line: 1,
                    rule: "unresolved_contract_token".to_string(),
                    message: format!(
                        "Component contract '{}' references non-existent design token '{}'",
                        name, tok_name
                    ),
                    severity: "error".to_string(),
                });
            }
        }
    }

    // 4. Token Freshness Verification
    if config.compiler.check_freshness_in_gate && config.compiler.tool != "none" {
        let freshness = check_tokens_freshness(root, config)?;
        if !freshness.is_fresh {
            if freshness.tool_available {
                is_compliant = false;
                violations.push(DesignLintViolation {
                    file: config.tokens_path.display().to_string(),
                    line: 1,
                    rule: "stale_compiled_tokens".to_string(),
                    message: format!(
                        "Compiled platform tokens are stale or missing (missing: {:?}, stale: {:?}). Run 'pa design compile' to update.",
                        freshness.missing_files, freshness.stale_files
                    ),
                    severity: "error".to_string(),
                });
                platform_results.insert(
                    "compiler".to_string(),
                    PlatformGateResult {
                        platform: "compiler".to_string(),
                        status: "failed".to_string(),
                        message: "Compiled design tokens are stale or missing.".to_string(),
                        details: vec![
                            format!("Missing files: {:?}", freshness.missing_files),
                            format!("Stale files: {:?}", freshness.stale_files),
                            "Run 'pa design compile' to synchronize platform token files."
                                .to_string(),
                        ],
                    },
                );
            } else if config
                .compiler
                .on_missing_tool
                .eq_ignore_ascii_case("block")
            {
                is_compliant = false;
                violations.push(DesignLintViolation {
                    file: config.tokens_path.display().to_string(),
                    line: 1,
                    rule: "missing_token_compiler".to_string(),
                    message: format!(
                        "Token compiler tool '{}' is required but missing on host.",
                        config.compiler.tool
                    ),
                    severity: "error".to_string(),
                });
                platform_results.insert(
                    "compiler".to_string(),
                    PlatformGateResult {
                        platform: "compiler".to_string(),
                        status: "failed".to_string(),
                        message: format!(
                            "Token compiler tool '{}' is missing on host (blocked).",
                            config.compiler.tool
                        ),
                        details: vec![format!("Error: {:?}", freshness.error)],
                    },
                );
            } else {
                // on_missing_tool == "skip"
                platform_results.insert(
                    "compiler".to_string(),
                    PlatformGateResult {
                        platform: "compiler".to_string(),
                        status: "skipped".to_string(),
                        message: format!(
                            "Token compiler tool '{}' is missing on host (skipped with warning).",
                            config.compiler.tool
                        ),
                        details: vec![format!("Warning: {:?}", freshness.warning)],
                    },
                );
            }
        } else {
            platform_results.insert(
                "compiler".to_string(),
                PlatformGateResult {
                    platform: "compiler".to_string(),
                    status: "passed".to_string(),
                    message: "Compiled design tokens are fresh.".to_string(),
                    details: Vec::new(),
                },
            );
        }
    }

    if violations.iter().any(|v| v.severity == "error") {
        is_compliant = false;
    }

    Ok(DesignGateReport {
        provider: store.provider,
        is_compliant,
        total_tokens: store.catalog.tokens.len(),
        total_contracts: store.contracts.len(),
        needs_design_review: drift_res.needs_design_review,
        new_components: drift_res.new_components,
        platform_results,
        violations,
        a11y_violations,
        visual_diff_failures,
    })
}

pub fn scan_workspace_for_lint(
    root: &Path,
    catalog: &TokenCatalog,
    violations: &mut Vec<DesignLintViolation>,
) -> Result<()> {
    let empty_contracts = HashMap::new();
    let drift_cfg = crate::schema::DesignDriftConfig::default();
    let res = scan_workspace_for_drift(root, &drift_cfg, &empty_contracts, catalog)?;
    violations.extend(res.violations);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;
    use tempfile::tempdir;

    #[test]
    fn test_parse_dtcg_tokens() {
        let json = r##"{
            "color": {
                "brand": {
                    "primary": {
                        "$value": "#2563eb",
                        "$type": "color",
                        "$description": "Primary action"
                    }
                }
            },
            "spacing": {
                "md": {
                    "$value": "16px",
                    "$type": "dimension"
                }
            }
        }"##;

        let catalog = TokenCatalog::from_json_str(json, "test.json").unwrap();
        assert_eq!(catalog.tokens.len(), 2);

        let primary = catalog.get("color.brand.primary").unwrap();
        assert_eq!(primary.value, "#2563eb");
        assert_eq!(primary.token_type, "color");
        assert_eq!(primary.description.as_deref(), Some("Primary action"));

        let spacing = catalog.get("spacing.md").unwrap();
        assert_eq!(spacing.value, "16px");
        assert_eq!(spacing.token_type, "dimension");
    }

    #[test]
    fn test_dtcg_alias_resolution() {
        let json = r##"{
            "color": {
                "core": {
                    "blue500": { "$value": "#3b82f6", "$type": "color" }
                },
                "brand": {
                    "primary": { "$value": "{color.core.blue500}", "$type": "color" }
                }
            }
        }"##;

        let catalog = TokenCatalog::from_json_str(json, "test.json").unwrap();
        let resolved = catalog.resolve_value("{color.brand.primary}");
        assert_eq!(resolved, "#3b82f6");
    }

    #[test]
    fn test_hardcoded_hex_detector() {
        assert_eq!(
            find_hardcoded_hex("const color = '#2563eb';"),
            Some("#2563eb".to_string())
        );
        assert_eq!(
            find_hardcoded_hex("Color(hex: \"#fff\")"),
            Some("#fff".to_string())
        );
        assert_eq!(find_hardcoded_hex("const id = '#main';"), None);
    }

    #[test]
    fn test_component_contract_parsing() {
        let toml_str = r#"
            name = "Button"
            description = "Interactive button"
            platforms = ["web", "ios"]
            tokens = ["color.brand.primary", "spacing.sm"]

            [web]
            component = "src/components/Button.tsx"
            catalog_entry = "Button.stories.tsx"
            a11y_target = "wcag2aa"

            [ios]
            component = "Sources/DesignSystem/Button.swift"
            catalog_entry = "ButtonPreviews.swift"
            a11y_target = "accessibilityElement"
        "#;

        let contract: ComponentContract = toml::from_str(toml_str).unwrap();
        assert_eq!(contract.name, "Button");
        assert_eq!(contract.platforms, vec!["web", "ios"]);
        assert_eq!(contract.tokens.len(), 2);
        assert_eq!(
            contract.web.as_ref().unwrap().component,
            "src/components/Button.tsx"
        );
        assert_eq!(
            contract.ios.as_ref().unwrap().component,
            "Sources/DesignSystem/Button.swift"
        );
    }

    #[test]
    fn test_evaluate_design_gate_none_provider() {
        let dir = tempdir().unwrap();
        let config = DesignSystemConfig {
            provider: "none".to_string(),
            ..Default::default()
        };

        let report = evaluate_design_gate(dir.path(), &config).unwrap();
        assert!(report.is_compliant);
        assert_eq!(report.provider, "none");
        assert_eq!(report.total_tokens, 0);
    }

    #[test]
    fn test_evaluate_design_gate_unresolved_token() {
        let dir = tempdir().unwrap();
        let contracts_dir = dir.path().join("design/contracts");
        fs::create_dir_all(&contracts_dir).unwrap();
        let contract_file = contracts_dir.join("button.toml");
        fs::write(
            &contract_file,
            r#"
            name = "Button"
            platforms = ["web"]
            tokens = ["non.existent.token"]
        "#,
        )
        .unwrap();

        let config = DesignSystemConfig {
            provider: "git_only".to_string(),
            tokens_path: PathBuf::from("design/tokens/tokens.json"),
            contracts_path: PathBuf::from("design/contracts"),
            platforms: vec![],
            compiler: crate::schema::TokenCompilerConfig {
                tool: "none".to_string(),
                ..Default::default()
            },
            ..Default::default()
        };

        let report = evaluate_design_gate(dir.path(), &config).unwrap();
        assert!(!report.is_compliant);
        assert_eq!(report.violations.len(), 1);
        assert_eq!(report.violations[0].rule, "unresolved_contract_token");
    }

    #[test]
    fn test_ast_drift_raw_primitives_tsx_swift_kt() {
        let dir = tempdir().unwrap();
        let mut contracts = HashMap::new();
        contracts.insert(
            "Button".to_string(),
            ComponentContract {
                name: "Button".to_string(),
                description: None,
                platforms: vec!["web".to_string(), "ios".to_string(), "android".to_string()],
                tokens: vec![],
                web: Some(WebContractBinding {
                    component: "src/ds/Button.tsx".to_string(),
                    catalog_entry: "".to_string(),
                    a11y_target: None,
                }),
                ios: None,
                android: None,
            },
        );

        let src_dir = dir.path().join("src");
        fs::create_dir_all(&src_dir).unwrap();

        // 1. TSX with raw <button> and commented raw <button>
        let tsx_file = src_dir.join("App.tsx");
        fs::write(
            &tsx_file,
            r#"
            // <button>in comment</button>
            /* <button>block comment</button> */
            export const App = () => {
                return (
                    <div>
                        <button onClick={() => {}}>Click Me</button>
                        <DSButton>Approved DS Button</DSButton>
                    </div>
                );
            };
            "#,
        )
        .unwrap();

        // 2. Swift with raw Button and new unregistered component
        let ios_dir = dir.path().join("ios");
        fs::create_dir_all(&ios_dir).unwrap();
        let swift_file = ios_dir.join("CardView.swift");
        fs::write(
            &swift_file,
            r#"
            // Button("in comment")
            public struct CardView: View {
                var body: some View {
                    Button(action: {}) {
                        Text("Click")
                    }
                }
            }
            "#,
        )
        .unwrap();

        // 3. Kotlin with raw Button
        let kt_dir = dir.path().join("android");
        fs::create_dir_all(&kt_dir).unwrap();
        let kt_file = kt_dir.join("Widget.kt");
        fs::write(
            &kt_file,
            r#"
            // Button(onClick = {})
            @Composable
            fun WidgetView() {
                Button(onClick = {}) {
                    Text("Click")
                }
            }
            "#,
        )
        .unwrap();

        let drift_cfg = crate::schema::DesignDriftConfig::default();
        let catalog = TokenCatalog::empty();
        let res = scan_workspace_for_drift(dir.path(), &drift_cfg, &contracts, &catalog).unwrap();

        assert_eq!(res.raw_primitive_violations, 3);
        assert!(res.needs_design_review);
        assert!(res.new_components.contains(&"CardView".to_string()));
        assert!(res.new_components.contains(&"WidgetView".to_string()));
    }

    #[test]
    fn test_ios_and_android_parser_fixtures() {
        let ios_a11y_json = r#"[
            { "id": "contrast_ratio", "impact": "serious", "description": "Contrast 2.1:1 below threshold", "target": "SubmitBtn" }
        ]"#;
        let ios_violations = parse_ios_a11y_output(ios_a11y_json);
        assert_eq!(ios_violations.len(), 1);
        assert_eq!(ios_violations[0].id, "contrast_ratio");

        let android_paparazzi_txt =
            "Paparazzi verification failed for [CheckoutScreen]: diff percentage was 0.08";
        let android_diffs = parse_android_visual_diff_output(android_paparazzi_txt, 0.05);
        assert_eq!(android_diffs.len(), 1);
        assert_eq!(android_diffs[0].snapshot_name, "CheckoutScreen");
        assert!(android_diffs[0].diff_pct > 0.05);
    }
}
