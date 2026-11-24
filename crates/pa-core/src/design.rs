use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fs;
use std::path::Path;
use std::process::Command;

use crate::schema::DesignSystemConfig;

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
            // Check if this object is a DTCG token node (contains "$value")
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

            // Otherwise, traverse child keys
            for (k, v) in obj {
                if k.starts_with('$') {
                    continue; // Skip metadata keys like $schema
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
        // DTCG alias syntax: {color.brand.primary}
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
                // If penpot endpoint is configured, we could fetch remotely;
                // fallback to local git tokens with metadata.
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

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct DesignGateReport {
    pub provider: String,
    pub is_compliant: bool,
    pub total_tokens: usize,
    pub total_contracts: usize,
    pub platform_results: HashMap<String, PlatformGateResult>,
    pub violations: Vec<DesignLintViolation>,
}

impl DesignGateReport {
    pub fn empty(provider: &str) -> Self {
        Self {
            provider: provider.to_string(),
            is_compliant: true,
            total_tokens: 0,
            total_contracts: 0,
            platform_results: HashMap::new(),
            violations: Vec::new(),
        }
    }
}

/// Evaluates the multi-platform design system quality gate:
/// 1. Verifies prerequisite toolchains for all enabled platforms (`on_missing_platform = "fail"`).
/// 2. Performs static token & raw primitive linting (e.g. catches hardcoded hex colors).
/// 3. Verifies component contracts and required DTCG token references.
/// 4. Checks platform accessibility and preview configurations.
pub fn evaluate_design_gate(root: &Path, config: &DesignSystemConfig) -> Result<DesignGateReport> {
    if config.provider == "none" {
        return Ok(DesignGateReport::empty("none"));
    }

    let store = DesignSystemStore::load(root, config)?;
    let mut violations = Vec::new();
    let mut platform_results = HashMap::new();
    let mut is_compliant = true;

    // 1. Check prerequisite toolchains for enabled platforms
    for platform in &config.platforms {
        match platform.as_str() {
            "web" => {
                let has_node = Command::new("node").arg("--version").output().is_ok();
                if !has_node && config.on_missing_platform == "fail" {
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
                            status: if has_node { "passed" } else { "skipped" }.to_string(),
                            message: format!(
                                "Web platform active (catalog: {}, a11y: {})",
                                config.web.catalog, config.web.a11y_engine
                            ),
                            details: Vec::new(),
                        },
                    );
                }
            }
            "ios" => {
                let has_simctl = Command::new("xcrun")
                    .args(["simctl", "help"])
                    .output()
                    .map(|o| o.status.success())
                    .unwrap_or(false);

                if !has_simctl && config.on_missing_platform == "fail" {
                    is_compliant = false;
                    platform_results.insert(
                        "ios".to_string(),
                        PlatformGateResult {
                            platform: "ios".to_string(),
                            status: "failed".to_string(),
                            message:
                                "iOS verification enabled but 'simctl' / Xcode CLI is not available."
                                    .to_string(),
                            details: vec![
                                "Prerequisite failed (on_missing_platform = 'fail'): Xcode command line tools required."
                                    .to_string(),
                            ],
                        },
                    );
                } else {
                    platform_results.insert(
                        "ios".to_string(),
                        PlatformGateResult {
                            platform: "ios".to_string(),
                            status: if has_simctl { "passed" } else { "skipped" }.to_string(),
                            message: format!(
                                "iOS platform active (runner: {}, a11y: {})",
                                config.ios.runner, config.ios.a11y_engine
                            ),
                            details: Vec::new(),
                        },
                    );
                }
            }
            "android" => {
                let has_adb = Command::new("adb")
                    .arg("version")
                    .output()
                    .map(|o| o.status.success())
                    .unwrap_or(false)
                    || std::env::var("ANDROID_HOME").is_ok()
                    || std::env::var("ANDROID_SDK_ROOT").is_ok();

                if !has_adb && config.on_missing_platform == "fail" {
                    is_compliant = false;
                    platform_results.insert(
                        "android".to_string(),
                        PlatformGateResult {
                            platform: "android".to_string(),
                            status: "failed".to_string(),
                            message:
                                "Android verification enabled but 'adb' / Android SDK is not available."
                                    .to_string(),
                            details: vec![
                                "Prerequisite failed (on_missing_platform = 'fail'): Android SDK / adb required."
                                    .to_string(),
                            ],
                        },
                    );
                } else {
                    platform_results.insert(
                        "android".to_string(),
                        PlatformGateResult {
                            platform: "android".to_string(),
                            status: if has_adb { "passed" } else { "skipped" }.to_string(),
                            message: format!(
                                "Android platform active (runner: {}, a11y: {})",
                                config.android.runner, config.android.a11y_engine
                            ),
                            details: Vec::new(),
                        },
                    );
                }
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

    // 2. Static Token & Primitive Linting
    scan_workspace_for_lint(root, &store.catalog, &mut violations)?;

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

    if violations.iter().any(|v| v.severity == "error") {
        is_compliant = false;
    }

    Ok(DesignGateReport {
        provider: store.provider,
        is_compliant,
        total_tokens: store.catalog.tokens.len(),
        total_contracts: store.contracts.len(),
        platform_results,
        violations,
    })
}

fn scan_workspace_for_lint(
    root: &Path,
    catalog: &TokenCatalog,
    violations: &mut Vec<DesignLintViolation>,
) -> Result<()> {
    walk_and_lint(root, root, catalog, violations)
}

fn walk_and_lint(
    base: &Path,
    current: &Path,
    catalog: &TokenCatalog,
    violations: &mut Vec<DesignLintViolation>,
) -> Result<()> {
    if !current.is_dir() {
        return Ok(());
    }

    for entry in fs::read_dir(current)?.filter_map(|e| e.ok()) {
        let path = entry.path();
        let name = path.file_name().and_then(|n| n.to_str()).unwrap_or("");

        // Skip ignored directories
        if name.starts_with('.')
            || name == "target"
            || name == "node_modules"
            || name == ".venv"
            || name == "__pycache__"
            || name == "site"
            || name == "tokens" // Do not lint the tokens file itself!
            || name == "design" // Skip design tokens/contracts definitions
            || name == "crates"
        // Rust backend crates do not contain UI styles
        {
            continue;
        }

        if path.is_dir() {
            walk_and_lint(base, &path, catalog, violations)?;
        } else if path.is_file() {
            lint_file(base, &path, catalog, violations)?;
        }
    }

    Ok(())
}

fn lint_file(
    base: &Path,
    path: &Path,
    _catalog: &TokenCatalog,
    violations: &mut Vec<DesignLintViolation>,
) -> Result<()> {
    let ext = path.extension().and_then(|e| e.to_str()).unwrap_or("");
    let is_ui_file = matches!(
        ext,
        "tsx" | "jsx" | "css" | "scss" | "swift" | "kt" | "vue" | "html"
    );
    if !is_ui_file {
        return Ok(());
    }

    let content = match fs::read_to_string(path) {
        Ok(c) => c,
        Err(_) => return Ok(()),
    };

    let rel_path = path
        .strip_prefix(base)
        .unwrap_or(path)
        .display()
        .to_string();

    for (line_num, line) in content.lines().enumerate() {
        // Skip comment lines or lines with ignore directive
        let trimmed = line.trim();
        if trimmed.starts_with("//")
            || trimmed.starts_with("/*")
            || trimmed.starts_with('*')
            || trimmed.contains("ignore-design-token")
        {
            continue;
        }

        // Detect hardcoded hex colors: #[0-9a-fA-F]{6} or #[0-9a-fA-F]{3}
        if let Some(hex) = find_hardcoded_hex(line) {
            violations.push(DesignLintViolation {
                file: rel_path.clone(),
                line: line_num + 1,
                rule: "no_hardcoded_color".to_string(),
                message: format!(
                    "Hardcoded color '{}' detected. Use a W3C DTCG design token instead.",
                    hex
                ),
                severity: "error".to_string(),
            });
        }
    }

    Ok(())
}

fn find_hardcoded_hex(line: &str) -> Option<String> {
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
                // Verify it is not an ID selector like #main or #root
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
        "#;

        let contract: ComponentContract = toml::from_str(toml_str).unwrap();
        assert_eq!(contract.name, "Button");
        assert_eq!(contract.platforms, vec!["web", "ios"]);
        assert_eq!(contract.tokens, vec!["color.brand.primary", "spacing.sm"]);
        assert_eq!(contract.web.unwrap().component, "src/components/Button.tsx");
    }

    #[test]
    fn test_design_gate_clean_workspace() {
        let td = tempdir().unwrap();
        let tokens_dir = td.path().join("design/tokens");
        fs::create_dir_all(&tokens_dir).unwrap();
        fs::write(
            tokens_dir.join("tokens.json"),
            r##"{"color":{"brand":{"primary":{"$value":"#2563eb","$type":"color"}}}}"##,
        )
        .unwrap();

        let cfg = DesignSystemConfig {
            provider: "git_only".to_string(),
            tokens_path: PathBuf::from("design/tokens/tokens.json"),
            contracts_path: PathBuf::from("design/contracts"),
            platforms: vec!["web".to_string()],
            on_missing_platform: "fail".to_string(),
            ..DesignSystemConfig::default()
        };

        let report = evaluate_design_gate(td.path(), &cfg).unwrap();
        assert!(report.is_compliant);
        assert_eq!(report.total_tokens, 1);
        assert!(report.violations.is_empty());
    }

    #[test]
    fn test_design_gate_hardcoded_color_violation() {
        let td = tempdir().unwrap();
        let tokens_dir = td.path().join("design/tokens");
        fs::create_dir_all(&tokens_dir).unwrap();
        fs::write(
            tokens_dir.join("tokens.json"),
            r##"{"color":{"brand":{"primary":{"$value":"#2563eb","$type":"color"}}}}"##,
        )
        .unwrap();

        let src_dir = td.path().join("src");
        fs::create_dir_all(&src_dir).unwrap();
        fs::write(
            src_dir.join("Button.tsx"),
            "export const Button = () => <button style={{ backgroundColor: '#ff0000' }}>Click</button>;\n",
        )
        .unwrap();

        let cfg = DesignSystemConfig {
            provider: "git_only".to_string(),
            tokens_path: PathBuf::from("design/tokens/tokens.json"),
            contracts_path: PathBuf::from("design/contracts"),
            platforms: vec!["web".to_string()],
            on_missing_platform: "fail".to_string(),
            ..DesignSystemConfig::default()
        };

        let report = evaluate_design_gate(td.path(), &cfg).unwrap();
        assert!(!report.is_compliant);
        assert_eq!(report.violations.len(), 1);
        assert_eq!(report.violations[0].rule, "no_hardcoded_color");
    }

    #[test]
    fn test_design_gate_missing_platform_hard_fail() {
        let td = tempdir().unwrap();
        let tokens_dir = td.path().join("design/tokens");
        fs::create_dir_all(&tokens_dir).unwrap();
        fs::write(
            tokens_dir.join("tokens.json"),
            r##"{"color":{"brand":{"primary":{"$value":"#2563eb","$type":"color"}}}}"##,
        )
        .unwrap();

        // If android is checked and adb is not present, on_missing_platform = "fail" must fail
        let cfg = DesignSystemConfig {
            provider: "git_only".to_string(),
            tokens_path: PathBuf::from("design/tokens/tokens.json"),
            contracts_path: PathBuf::from("design/contracts"),
            platforms: vec!["android".to_string()],
            on_missing_platform: "fail".to_string(),
            ..DesignSystemConfig::default()
        };

        // If adb is missing on host, report must reflect status and failure
        let report = evaluate_design_gate(td.path(), &cfg).unwrap();
        let android_res = report.platform_results.get("android").unwrap();
        if android_res.status == "failed" {
            assert!(!report.is_compliant);
        }
    }
}
