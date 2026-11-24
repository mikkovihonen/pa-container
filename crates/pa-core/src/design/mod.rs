pub mod a11y;
pub mod android;
pub mod compiler;
pub mod drift;
pub mod ios;
pub mod visual_diff;

use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fs;
use std::path::Path;

use crate::schema::DesignSystemConfig;

pub use a11y::{
    parse_axe_violations_json, run_android_a11y, run_ios_a11y, run_web_a11y, A11yExecutionReport,
    A11yViolation,
};
pub use android::{
    evaluate_android_platform, parse_android_a11y_output, parse_android_visual_diff_output,
};
pub use compiler::{
    check_tokens_freshness, check_tool_availability, compile_design_tokens, compute_file_digest,
    TokenCompileReport, TokenFreshnessReport,
};
pub use drift::{find_hardcoded_hex, scan_workspace_for_drift, DriftScanResult};
pub use ios::{evaluate_ios_platform, parse_ios_a11y_output, parse_ios_visual_diff_output};
pub use visual_diff::{
    compare_baseline_directory, compare_png_bytes, compare_snapshot_file,
    parse_android_visual_diff_output as parse_android_visual_diff,
    parse_ios_visual_diff_output as parse_ios_visual_diff, parse_playwright_visual_diff_json,
    run_android_visual_diff, run_ios_visual_diff, run_web_visual_diff, PixelDiffResult,
    VisualDiffExecutionReport, VisualDiffFailure,
};

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
    #[serde(default)]
    pub failed_snapshots: usize,
    #[serde(default)]
    pub visual_diff_pct: f64,
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
            failed_snapshots: 0,
            visual_diff_pct: 0.0,
        }
    }
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
                let a11y_rep = a11y::run_web_a11y(root, &config.web, config)?;
                let visual_rep = visual_diff::run_web_visual_diff(root, &config.web, config)?;

                if !a11y_rep.passed || !visual_rep.passed {
                    is_compliant = false;
                }

                for v in &a11y_rep.violations {
                    if v.is_blocking() {
                        violations.push(DesignLintViolation {
                            file: v.target.clone().unwrap_or_else(|| "web".to_string()),
                            line: 1,
                            rule: "a11y_wcag_violation".to_string(),
                            message: format!(
                                "[axe-core] WCAG {} {} violation in '{}': {}",
                                config.web.wcag_level, v.impact, v.id, v.description
                            ),
                            severity: "error".to_string(),
                        });
                    }
                }
                for d in &visual_rep.failures {
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
                }

                a11y_violations.extend(a11y_rep.violations);
                visual_diff_failures.extend(visual_rep.failures);

                let status = if !a11y_rep.passed || !visual_rep.passed {
                    if a11y_rep.message.contains("missing (skipped")
                        && visual_rep.message.contains("missing (skipped")
                    {
                        "skipped".to_string()
                    } else {
                        "failed".to_string()
                    }
                } else if a11y_rep.message.contains("skipped")
                    && visual_rep.message.contains("skipped")
                {
                    "skipped".to_string()
                } else {
                    "passed".to_string()
                };

                let details = vec![a11y_rep.message, visual_rep.message];

                platform_results.insert(
                    "web".to_string(),
                    PlatformGateResult {
                        platform: "web".to_string(),
                        status,
                        message: format!(
                            "Web platform active (catalog: {}, a11y: {}, visual: {})",
                            config.web.catalog, config.web.a11y_engine, config.web.visual_diff_tool
                        ),
                        details,
                    },
                );
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

    let max_diff_pct = visual_diff_failures
        .iter()
        .map(|f| f.diff_pct)
        .fold(0.0f64, f64::max);
    let failed_snapshots = visual_diff_failures.len();

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
        failed_snapshots,
        visual_diff_pct: max_diff_pct,
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

    #[test]
    fn test_dynamic_web_axe_and_playwright_gate() {
        let td = tempfile::tempdir().unwrap();
        let root = td.path();

        // Create mock design tokens
        let tokens_dir = root.join("design/tokens");
        fs::create_dir_all(&tokens_dir).unwrap();
        fs::write(
            tokens_dir.join("tokens.json"),
            r##"{"color": {"brand": {"$value": "#ff0000", "$type": "color"}}}"##,
        )
        .unwrap();

        let config = DesignSystemConfig {
            platforms: vec!["web".to_string()],
            web: crate::schema::WebPlatformSpec {
                wcag_level: "AA".to_string(),
                max_visual_diff_pct: 0.05,
                a11y_command: Some(
                    r#"printf '{"violations": [{"id": "color-contrast", "impact": "serious", "description": "Element has insufficient contrast", "tags": ["wcag2aa"], "nodes": [{"target": ["button.cta"]}]}]}'"#.to_string(),
                ),
                visual_diff_command: Some(
                    r##"printf '[{"snapshot": "hero-banner", "diff_pct": 0.08, "expected": "base.png", "actual": "curr.png"}]'"##.to_string(),
                ),
                ..Default::default()
            },
            ..Default::default()
        };

        let report = evaluate_design_gate(root, &config).unwrap();
        assert!(!report.is_compliant);
        assert_eq!(report.a11y_violations.len(), 1);
        assert_eq!(report.a11y_violations[0].id, "color-contrast");
        assert_eq!(report.visual_diff_failures.len(), 1);
        assert_eq!(report.visual_diff_failures[0].snapshot_name, "hero-banner");

        let web_res = report.platform_results.get("web").unwrap();
        assert_eq!(web_res.status, "failed");
    }

    #[test]
    fn test_dynamic_ios_and_android_report_fallbacks_and_missing_tool() {
        use crate::schema::{AndroidPlatformSpec, IosPlatformSpec};

        let td = tempfile::tempdir().unwrap();
        let root = td.path();

        // Staged reports in .pa/reports/
        let rep_dir = root.join(".pa/reports");
        fs::create_dir_all(&rep_dir).unwrap();

        // Staged iOS a11y report
        fs::write(
            rep_dir.join("ios-a11y.json"),
            r#"[{"id": "accessibility_label_missing", "impact": "serious", "description": "Button lacks accessibility label", "target": "BuyNow"}]"#,
        )
        .unwrap();

        // Staged Android visual diff report
        fs::write(
            rep_dir.join("android-visual-diff.json"),
            r#"Paparazzi verification failed for [ProfileScreen]: diff percentage was 0.12"#,
        )
        .unwrap();

        let base_cfg = DesignSystemConfig::default();

        // Evaluate iOS platform with staged report
        let ios_spec = IosPlatformSpec {
            enabled: true,
            ..Default::default()
        };
        let ios_res = evaluate_ios_platform(root, &ios_spec, &base_cfg).unwrap();
        assert_eq!(ios_res.gate_result.status, "failed");
        assert_eq!(ios_res.a11y_violations.len(), 1);
        assert_eq!(ios_res.a11y_violations[0].id, "accessibility_label_missing");

        // Evaluate Android platform with staged report
        let android_spec = AndroidPlatformSpec {
            enabled: true,
            ..Default::default()
        };
        let android_res = evaluate_android_platform(root, &android_spec, &base_cfg).unwrap();
        assert_eq!(android_res.gate_result.status, "failed");
        assert_eq!(android_res.visual_diff_failures.len(), 1);
        assert_eq!(
            android_res.visual_diff_failures[0].snapshot_name,
            "ProfileScreen"
        );

        // Clean directory: test on_missing_platform = 'skip' vs 'block'
        let empty_td = tempfile::tempdir().unwrap();
        let empty_root = empty_td.path();

        let skip_spec = IosPlatformSpec {
            enabled: true,
            on_missing_platform: "skip".to_string(),
            ..Default::default()
        };
        let skip_res = evaluate_ios_platform(empty_root, &skip_spec, &base_cfg).unwrap();
        assert_eq!(skip_res.gate_result.status, "skipped");

        let block_spec = IosPlatformSpec {
            enabled: true,
            on_missing_platform: "block".to_string(),
            ..Default::default()
        };
        let block_res = evaluate_ios_platform(empty_root, &block_spec, &base_cfg).unwrap();
        // If host has xcrun simctl it might run or fail prerequisite
        let has_simctl = std::process::Command::new("xcrun")
            .args(["simctl", "help"])
            .output()
            .map(|o| o.status.success())
            .unwrap_or(false);
        if !has_simctl {
            assert_eq!(block_res.gate_result.status, "failed");
        }
    }
}
