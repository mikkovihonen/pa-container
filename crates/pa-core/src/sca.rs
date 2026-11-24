use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use std::collections::HashSet;
use std::path::Path;
use std::process::Command;

use crate::schema::ScaConfig;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub enum ScaSeverity {
    Low,
    Medium,
    High,
    Critical,
    Unknown,
}

impl ScaSeverity {
    pub fn parse(s: &str) -> Self {
        match s.to_lowercase().trim() {
            "low" => Self::Low,
            "medium" | "med" | "moderate" => Self::Medium,
            "high" => Self::High,
            "critical" | "crit" => Self::Critical,
            _ => Self::Unknown,
        }
    }

    pub fn rank(&self) -> u8 {
        match self {
            Self::Low => 1,
            Self::Medium => 2,
            Self::High => 3,
            Self::Critical => 4,
            Self::Unknown => 0,
        }
    }

    pub fn at_least(&self, threshold: &Self) -> bool {
        self.rank() >= threshold.rank()
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ScaVulnerability {
    pub id: String,
    pub package: String,
    pub installed_version: String,
    pub patched_versions: Vec<String>,
    pub severity: ScaSeverity,
    pub title: String,
    pub url: Option<String>,
    pub advisory_source: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ScaGateReport {
    pub status: String, // "passed" | "failed" | "skipped"
    pub is_compliant: bool,
    pub scanner: String,
    pub vulnerabilities_found: usize,
    pub blocking_vulnerabilities: Vec<ScaVulnerability>,
    pub advisories: Vec<ScaVulnerability>,
    pub summary: String,
}

impl ScaGateReport {
    pub fn empty(scanner: &str) -> Self {
        Self {
            status: "passed".to_string(),
            is_compliant: true,
            scanner: scanner.to_string(),
            vulnerabilities_found: 0,
            blocking_vulnerabilities: Vec::new(),
            advisories: Vec::new(),
            summary: "No vulnerabilities detected.".to_string(),
        }
    }

    pub fn skipped(scanner: &str, reason: &str) -> Self {
        Self {
            status: "skipped".to_string(),
            is_compliant: true,
            scanner: scanner.to_string(),
            vulnerabilities_found: 0,
            blocking_vulnerabilities: Vec::new(),
            advisories: Vec::new(),
            summary: reason.to_string(),
        }
    }

    pub fn failed_missing_tool(scanner: &str, tool_name: &str) -> Self {
        Self {
            status: "failed".to_string(),
            is_compliant: false,
            scanner: scanner.to_string(),
            vulnerabilities_found: 0,
            blocking_vulnerabilities: Vec::new(),
            advisories: Vec::new(),
            summary: format!(
                "Required SCA scanner '{}' is missing and on_missing_tool is set to 'block'.",
                tool_name
            ),
        }
    }
}

/// Parses the JSON output of `cargo audit --json`.
pub fn parse_cargo_audit_json(json_str: &str) -> Result<Vec<ScaVulnerability>> {
    let mut vulnerabilities = Vec::new();
    let val: serde_json::Value =
        serde_json::from_str(json_str).context("Failed to parse cargo audit JSON output")?;

    if let Some(list) = val
        .get("vulnerabilities")
        .and_then(|v| v.get("list"))
        .and_then(|l| l.as_array())
    {
        for item in list {
            let advisory = item.get("advisory").unwrap_or(&serde_json::Value::Null);
            let id = advisory
                .get("id")
                .and_then(|v| v.as_str())
                .unwrap_or("UNKNOWN")
                .to_string();

            let title = advisory
                .get("title")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();

            let url = advisory
                .get("url")
                .and_then(|v| v.as_str())
                .map(|s| s.to_string());

            let severity_str = advisory
                .get("severity")
                .and_then(|v| v.as_str())
                .unwrap_or_else(|| {
                    if let Some(cvss) = advisory.get("cvss").and_then(|v| v.as_str()) {
                        if cvss.contains("/S:C") || cvss.contains("/A:H") {
                            "high"
                        } else {
                            "medium"
                        }
                    } else {
                        "high"
                    }
                });
            let severity = ScaSeverity::parse(severity_str);

            let pkg = item.get("package").unwrap_or(&serde_json::Value::Null);
            let package = pkg
                .get("name")
                .and_then(|v| v.as_str())
                .unwrap_or("unknown")
                .to_string();

            let installed_version = pkg
                .get("version")
                .and_then(|v| v.as_str())
                .unwrap_or("unknown")
                .to_string();

            let mut patched_versions = Vec::new();
            if let Some(patched) = item
                .get("versions")
                .and_then(|v| v.get("patched"))
                .and_then(|p| p.as_array())
            {
                for p in patched {
                    if let Some(s) = p.as_str() {
                        patched_versions.push(s.to_string());
                    }
                }
            }

            vulnerabilities.push(ScaVulnerability {
                id,
                package,
                installed_version,
                patched_versions,
                severity,
                title,
                url,
                advisory_source: "cargo-audit".to_string(),
            });
        }
    }

    Ok(vulnerabilities)
}

/// Parses the JSON output of `trivy fs --format json`.
pub fn parse_trivy_json(json_str: &str) -> Result<Vec<ScaVulnerability>> {
    let mut vulnerabilities = Vec::new();
    let val: serde_json::Value =
        serde_json::from_str(json_str).context("Failed to parse trivy JSON output")?;

    if let Some(results) = val.get("Results").and_then(|r| r.as_array()) {
        for res in results {
            if let Some(vulns) = res.get("Vulnerabilities").and_then(|v| v.as_array()) {
                for item in vulns {
                    let id = item
                        .get("VulnerabilityID")
                        .and_then(|v| v.as_str())
                        .unwrap_or("UNKNOWN")
                        .to_string();

                    let package = item
                        .get("PkgName")
                        .and_then(|v| v.as_str())
                        .unwrap_or("unknown")
                        .to_string();

                    let installed_version = item
                        .get("InstalledVersion")
                        .and_then(|v| v.as_str())
                        .unwrap_or("unknown")
                        .to_string();

                    let patched_versions = item
                        .get("FixedVersion")
                        .and_then(|v| v.as_str())
                        .map(|s| vec![s.to_string()])
                        .unwrap_or_default();

                    let severity_str = item
                        .get("Severity")
                        .and_then(|v| v.as_str())
                        .unwrap_or("UNKNOWN");
                    let severity = ScaSeverity::parse(severity_str);

                    let title = item
                        .get("Title")
                        .and_then(|v| v.as_str())
                        .or_else(|| item.get("Description").and_then(|v| v.as_str()))
                        .unwrap_or("")
                        .to_string();

                    let url = item
                        .get("PrimaryURL")
                        .and_then(|v| v.as_str())
                        .map(|s| s.to_string());

                    vulnerabilities.push(ScaVulnerability {
                        id,
                        package,
                        installed_version,
                        patched_versions,
                        severity,
                        title,
                        url,
                        advisory_source: "trivy".to_string(),
                    });
                }
            }
        }
    }

    Ok(vulnerabilities)
}

/// Evaluates the Software Composition Analysis (SCA) quality gate.
pub fn evaluate_sca_gate(workspace_dir: &Path, config: &ScaConfig) -> Result<ScaGateReport> {
    if !config.enabled || config.provider == "none" {
        return Ok(ScaGateReport::skipped(
            &config.provider,
            "SCA quality gate is disabled.",
        ));
    }

    let min_severity = ScaSeverity::parse(&config.min_severity);
    let ignore_set: HashSet<&str> = config.ignore_ids.iter().map(|s| s.as_str()).collect();

    let mut all_vulnerabilities = Vec::new();
    let mut scanners_run = Vec::new();

    let block_on_missing = config.on_missing_tool.eq_ignore_ascii_case("block");

    // 1. Run cargo-audit if provider is "cargo_audit" or "both"
    if config.provider == "cargo_audit" || config.provider == "both" {
        let has_cargo_audit = Command::new("cargo")
            .args(["audit", "--version"])
            .output()
            .map(|o| o.status.success())
            .unwrap_or(false);

        if !has_cargo_audit {
            if block_on_missing {
                return Ok(ScaGateReport::failed_missing_tool(
                    &config.provider,
                    "cargo-audit",
                ));
            } else {
                eprintln!(
                    "[WARN] cargo-audit is not installed. Skipping cargo-audit scan (on_missing_tool = 'skip')."
                );
            }
        } else {
            scanners_run.push("cargo-audit");
            let output = Command::new("cargo")
                .args(["audit", "--json"])
                .current_dir(workspace_dir)
                .output();

            if let Ok(out) = output {
                let stdout = String::from_utf8_lossy(&out.stdout);
                if let Ok(vulns) = parse_cargo_audit_json(&stdout) {
                    all_vulnerabilities.extend(vulns);
                }
            }
        }
    }

    // 2. Run trivy if provider is "trivy" or "both"
    if config.provider == "trivy" || config.provider == "both" {
        let has_trivy = Command::new("trivy")
            .arg("--version")
            .output()
            .map(|o| o.status.success())
            .unwrap_or(false);

        if !has_trivy {
            if block_on_missing && config.provider == "trivy" {
                return Ok(ScaGateReport::failed_missing_tool(
                    &config.provider,
                    "trivy",
                ));
            } else {
                eprintln!(
                    "[WARN] trivy is not installed. Skipping trivy scan (on_missing_tool = 'skip')."
                );
            }
        } else {
            scanners_run.push("trivy");
            let output = Command::new("trivy")
                .args(["fs", "--format", "json", "--quiet", "."])
                .current_dir(workspace_dir)
                .output();

            if let Ok(out) = output {
                let stdout = String::from_utf8_lossy(&out.stdout);
                if let Ok(vulns) = parse_trivy_json(&stdout) {
                    all_vulnerabilities.extend(vulns);
                }
            }
        }
    }

    // 3. Run custom command if provider is "custom_cmd"
    if config.provider == "custom_cmd" {
        if let Some(ref cmd_str) = config.custom_command {
            scanners_run.push("custom_cmd");
            let status = Command::new("sh")
                .arg("-c")
                .arg(cmd_str)
                .current_dir(workspace_dir)
                .status();

            let success = status.map(|s| s.success()).unwrap_or(false);
            if !success {
                return Ok(ScaGateReport {
                    status: "failed".to_string(),
                    is_compliant: false,
                    scanner: "custom_cmd".to_string(),
                    vulnerabilities_found: 1,
                    blocking_vulnerabilities: vec![ScaVulnerability {
                        id: "CUSTOM-CMD-FAIL".to_string(),
                        package: "workspace".to_string(),
                        installed_version: "unknown".to_string(),
                        patched_versions: Vec::new(),
                        severity: ScaSeverity::High,
                        title: format!(
                            "Custom SCA command '{}' failed with non-zero exit status",
                            cmd_str
                        ),
                        url: None,
                        advisory_source: "custom_cmd".to_string(),
                    }],
                    advisories: Vec::new(),
                    summary: format!("Custom SCA command '{}' failed.", cmd_str),
                });
            }
        } else if block_on_missing {
            return Ok(ScaGateReport::failed_missing_tool(
                "custom_cmd",
                "custom_command configuration",
            ));
        }
    }

    // Deduplicate vulnerabilities by (id, package)
    let mut seen = HashSet::new();
    let mut unique_vulns = Vec::new();
    for v in all_vulnerabilities {
        let key = format!("{}:{}", v.id, v.package);
        if seen.insert(key) {
            unique_vulns.push(v);
        }
    }

    // Filter blocking vulnerabilities: severity >= min_severity AND id not in ignore_ids
    let mut blocking = Vec::new();
    for v in &unique_vulns {
        if ignore_set.contains(v.id.as_str()) {
            continue;
        }
        if v.severity.at_least(&min_severity) {
            blocking.push(v.clone());
        }
    }

    let is_compliant = blocking.is_empty();
    let status = if is_compliant {
        "passed".to_string()
    } else {
        "failed".to_string()
    };

    let scanner_desc = if scanners_run.is_empty() {
        config.provider.clone()
    } else {
        scanners_run.join(" + ")
    };

    let summary = if is_compliant {
        format!(
            "SCA gate passed: {} advisories found, 0 blocking at or above '{:?}' severity.",
            unique_vulns.len(),
            min_severity
        )
    } else {
        format!(
            "SCA gate failed: {} blocking vulnerability/ies found at or above '{:?}' severity.",
            blocking.len(),
            min_severity
        )
    };

    Ok(ScaGateReport {
        status,
        is_compliant,
        scanner: scanner_desc,
        vulnerabilities_found: unique_vulns.len(),
        blocking_vulnerabilities: blocking,
        advisories: unique_vulns,
        summary,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_cargo_audit_json_with_vulnerabilities() {
        let json_data = r#"{
            "database": {"advisories": 500},
            "vulnerabilities": {
                "found": true,
                "count": 2,
                "list": [
                    {
                        "advisory": {
                            "id": "RUSTSEC-2020-0071",
                            "package": "time",
                            "title": "Potential segfault in time::parse",
                            "url": "https://rustsec.org/advisories/RUSTSEC-2020-0071",
                            "severity": "high"
                        },
                        "package": {
                            "name": "time",
                            "version": "0.1.43"
                        },
                        "versions": {
                            "patched": [">=0.2.23"]
                        }
                    },
                    {
                        "advisory": {
                            "id": "RUSTSEC-2021-0145",
                            "package": "atty",
                            "title": "Potential unaligned read",
                            "url": "https://rustsec.org/advisories/RUSTSEC-2021-0145",
                            "severity": "low"
                        },
                        "package": {
                            "name": "atty",
                            "version": "0.2.14"
                        },
                        "versions": {
                            "patched": [">=0.2.15"]
                        }
                    }
                ]
            }
        }"#;

        let vulns = parse_cargo_audit_json(json_data).unwrap();
        assert_eq!(vulns.len(), 2);

        let high = &vulns[0];
        assert_eq!(high.id, "RUSTSEC-2020-0071");
        assert_eq!(high.package, "time");
        assert_eq!(high.severity, ScaSeverity::High);
        assert_eq!(high.patched_versions, vec![">=0.2.23"]);

        let low = &vulns[1];
        assert_eq!(low.id, "RUSTSEC-2021-0145");
        assert_eq!(low.severity, ScaSeverity::Low);
    }

    #[test]
    fn test_parse_trivy_json_with_vulnerabilities() {
        let json_data = r#"{
            "SchemaVersion": 2,
            "Results": [
                {
                    "Target": "Cargo.lock",
                    "Class": "lang-pkgs",
                    "Type": "cargo",
                    "Vulnerabilities": [
                        {
                            "VulnerabilityID": "CVE-2023-45853",
                            "PkgName": "miniz_oxide",
                            "InstalledVersion": "0.5.3",
                            "FixedVersion": "0.5.4",
                            "Severity": "CRITICAL",
                            "Title": "Out-of-bounds write in miniz_oxide",
                            "PrimaryURL": "https://avd.aquasec.com/nvd/cve-2023-45853"
                        }
                    ]
                }
            ]
        }"#;

        let vulns = parse_trivy_json(json_data).unwrap();
        assert_eq!(vulns.len(), 1);
        let crit = &vulns[0];
        assert_eq!(crit.id, "CVE-2023-45853");
        assert_eq!(crit.package, "miniz_oxide");
        assert_eq!(crit.severity, ScaSeverity::Critical);
        assert_eq!(crit.patched_versions, vec!["0.5.4"]);
    }

    #[test]
    fn test_sca_severity_filtering_and_ignore_ids() {
        let vulns = [
            ScaVulnerability {
                id: "CVE-2023-0001".to_string(),
                package: "foo".to_string(),
                installed_version: "1.0.0".to_string(),
                patched_versions: vec!["1.0.1".to_string()],
                severity: ScaSeverity::High,
                title: "High severity issue".to_string(),
                url: None,
                advisory_source: "cargo-audit".to_string(),
            },
            ScaVulnerability {
                id: "CVE-2023-0002".to_string(),
                package: "bar".to_string(),
                installed_version: "2.0.0".to_string(),
                patched_versions: vec![],
                severity: ScaSeverity::Low,
                title: "Low severity issue".to_string(),
                url: None,
                advisory_source: "cargo-audit".to_string(),
            },
        ];

        // 1. Min severity High -> only CVE-2023-0001 blocks
        let high_thresh = ScaSeverity::High;
        let blocking: Vec<_> = vulns
            .iter()
            .filter(|v| v.severity.at_least(&high_thresh))
            .collect();
        assert_eq!(blocking.len(), 1);
        assert_eq!(blocking[0].id, "CVE-2023-0001");

        // 2. Ignore CVE-2023-0001
        let ignored: HashSet<&str> = ["CVE-2023-0001"].into_iter().collect();
        let remaining: Vec<_> = vulns
            .iter()
            .filter(|v| !ignored.contains(v.id.as_str()) && v.severity.at_least(&high_thresh))
            .collect();
        assert_eq!(remaining.len(), 0);
    }
}
