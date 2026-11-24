pub mod coverage;
pub mod junit;
pub mod oft;
pub mod strictdoc;

use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::Path;

pub use coverage::{CoverageReport, FileCoverage};
pub use junit::{JUnitReport, TestCase, TestOutcome, TestSuite};
pub use oft::OpenFastTraceScanner;
pub use strictdoc::StrictDocEngine;

use crate::schema::TraceabilityConfig;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct RequirementCoverage {
    pub req_id: String,
    pub has_impl: bool,
    pub has_test: bool,
    pub impl_locations: Vec<String>,
    pub test_locations: Vec<String>,
    #[serde(default)]
    pub test_passed: bool,
    #[serde(default)]
    pub test_executed: bool,
    #[serde(default)]
    pub line_coverage_pct: Option<f64>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct TraceabilityReport {
    pub engine: String,
    pub total_requirements: usize,
    pub covered_requirements: usize,
    pub missing_impl: Vec<String>,
    pub missing_tests: Vec<String>,
    pub coverage_pct: f64,
    pub is_compliant: bool,
    pub details: HashMap<String, RequirementCoverage>,
    #[serde(default)]
    pub tests_passed: usize,
    #[serde(default)]
    pub tests_failed: usize,
    #[serde(default)]
    pub tests_unexecuted: usize,
    #[serde(default)]
    pub line_coverage_pct: Option<f64>,
    #[serde(default)]
    pub uncovered_req_ids: Vec<String>,
    #[serde(default)]
    pub failing_req_ids: Vec<String>,
    #[serde(default)]
    pub unexecuted_req_ids: Vec<String>,
    #[serde(default)]
    pub orphaned_links: Vec<String>,
    #[serde(default)]
    pub report_artifact: Option<String>,
}

impl TraceabilityReport {
    pub fn empty(engine: &str) -> Self {
        Self {
            engine: engine.to_string(),
            total_requirements: 0,
            covered_requirements: 0,
            missing_impl: Vec::new(),
            missing_tests: Vec::new(),
            coverage_pct: 100.0,
            is_compliant: true,
            details: HashMap::new(),
            tests_passed: 0,
            tests_failed: 0,
            tests_unexecuted: 0,
            line_coverage_pct: None,
            uncovered_req_ids: Vec::new(),
            failing_req_ids: Vec::new(),
            unexecuted_req_ids: Vec::new(),
            orphaned_links: Vec::new(),
            report_artifact: None,
        }
    }
}

pub fn evaluate_traceability_gate(
    root: &Path,
    config: &TraceabilityConfig,
) -> Result<TraceabilityReport> {
    match config.engine.to_lowercase().as_str() {
        "none" => Ok(TraceabilityReport::empty("none")),
        "strictdoc" => StrictDocEngine::scan(root, config),
        "custom_cmd" => {
            if let Some(ref cmd_str) = config.custom_cmd {
                let status = std::process::Command::new("sh")
                    .arg("-c")
                    .arg(cmd_str)
                    .current_dir(root)
                    .status()
                    .with_context(|| {
                        format!("Failed to run custom traceability command: {}", cmd_str)
                    })?;

                let is_compliant = status.success();
                let coverage_pct = if is_compliant { 100.0 } else { 0.0 };
                Ok(TraceabilityReport {
                    engine: "custom_cmd".to_string(),
                    total_requirements: 1,
                    covered_requirements: if is_compliant { 1 } else { 0 },
                    missing_impl: Vec::new(),
                    missing_tests: Vec::new(),
                    coverage_pct,
                    is_compliant,
                    details: HashMap::new(),
                    tests_passed: if is_compliant { 1 } else { 0 },
                    tests_failed: if is_compliant { 0 } else { 1 },
                    tests_unexecuted: 0,
                    line_coverage_pct: None,
                    uncovered_req_ids: Vec::new(),
                    failing_req_ids: Vec::new(),
                    unexecuted_req_ids: Vec::new(),
                    orphaned_links: Vec::new(),
                    report_artifact: None,
                })
            } else {
                anyhow::bail!("custom_cmd engine selected but no custom_cmd string configured");
            }
        }
        _ => OpenFastTraceScanner::scan(root, config),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use tempfile::tempdir;

    #[test]
    fn test_oft_scanner_full_compliance_with_junit() {
        let td = tempdir().unwrap();
        let spec_file = td.path().join("spec.md");
        let src_file = td.path().join("auth.rs");
        let test_file = td.path().join("auth_test.rs");

        fs::write(
            spec_file,
            "# Requirements\n- req~AUTH-TOKEN~1: Token rotation\n",
        )
        .unwrap();
        fs::write(src_file, "// impl~AUTH-TOKEN~1\npub fn rotate_token() {}\n").unwrap();
        fs::write(
            test_file,
            "// utest~AUTH-TOKEN~1\n#[test]\nfn test_rotate() {}\n",
        )
        .unwrap();

        let reports_dir = td.path().join(".pa/reports");
        fs::create_dir_all(&reports_dir).unwrap();
        let junit_xml = r#"<testsuite name="auth">
    <testcase name="test_rotate" classname="auth_test" file="auth_test.rs" time="0.01"/>
</testsuite>"#;
        fs::write(reports_dir.join("junit.xml"), junit_xml).unwrap();

        let cfg = TraceabilityConfig {
            engine: "openfasttrace".to_string(),
            min_coverage_pct: 95.0,
            enforce_test_linkage: true,
            require_test_execution: true,
            junit_report_paths: vec![".pa/reports/junit.xml".to_string()],
            ..Default::default()
        };

        let report = OpenFastTraceScanner::scan(td.path(), &cfg).unwrap();
        assert_eq!(report.total_requirements, 1);
        assert_eq!(report.covered_requirements, 1);
        assert_eq!(report.tests_passed, 1);
        assert_eq!(report.tests_failed, 0);
        assert!(report.is_compliant);
    }

    #[test]
    fn test_oft_scanner_failing_junit_fails_gate() {
        let td = tempdir().unwrap();
        let spec_file = td.path().join("spec.md");
        let src_file = td.path().join("auth.rs");
        let test_file = td.path().join("auth_test.rs");

        fs::write(spec_file, "- req~AUTH-TOKEN~1: Token rotation\n").unwrap();
        fs::write(src_file, "// impl~AUTH-TOKEN~1\nfn rotate() {}\n").unwrap();
        fs::write(
            test_file,
            "// utest~AUTH-TOKEN~1\n#[test]\nfn test_rotate() {}\n",
        )
        .unwrap();

        let reports_dir = td.path().join(".pa/reports");
        fs::create_dir_all(&reports_dir).unwrap();
        let junit_xml = r#"<testsuite name="auth">
    <testcase name="test_rotate" classname="auth_test" file="auth_test.rs" time="0.01">
        <failure message="timeout">execution timed out</failure>
    </testcase>
</testsuite>"#;
        fs::write(reports_dir.join("junit.xml"), junit_xml).unwrap();

        let cfg = TraceabilityConfig {
            engine: "openfasttrace".to_string(),
            min_coverage_pct: 95.0,
            enforce_test_linkage: true,
            require_test_execution: true,
            junit_report_paths: vec![".pa/reports/junit.xml".to_string()],
            ..Default::default()
        };

        let report = OpenFastTraceScanner::scan(td.path(), &cfg).unwrap();
        assert_eq!(report.covered_requirements, 0);
        assert_eq!(report.tests_failed, 1);
        assert!(!report.is_compliant);
        assert_eq!(report.failing_req_ids, vec!["AUTH-TOKEN"]);
    }

    #[test]
    fn test_line_coverage_threshold_enforcement() {
        let td = tempdir().unwrap();
        let spec_file = td.path().join("spec.md");
        let src_file = td.path().join("auth.rs");
        let test_file = td.path().join("auth_test.rs");

        fs::write(spec_file, "- req~AUTH-TOKEN~1: Token rotation\n").unwrap();
        fs::write(src_file, "// impl~AUTH-TOKEN~1\nfn rotate() {}\n").unwrap();
        fs::write(
            test_file,
            "// utest~AUTH-TOKEN~1\n#[test]\nfn test_rotate() {}\n",
        )
        .unwrap();

        let reports_dir = td.path().join(".pa/reports");
        fs::create_dir_all(&reports_dir).unwrap();
        let lcov = r#"
SF:auth.rs
DA:1,1
DA:2,0
DA:3,0
DA:4,0
LF:4
LH:1
end_of_record
"#;
        fs::write(reports_dir.join("lcov.info"), lcov).unwrap();

        let cfg = TraceabilityConfig {
            engine: "openfasttrace".to_string(),
            min_coverage_pct: 95.0,
            enforce_test_linkage: true,
            require_test_execution: false,
            min_line_coverage_pct: Some(80.0), // actual is 25.0%
            coverage_report_path: Some(".pa/reports/lcov.info".to_string()),
            ..Default::default()
        };

        let report = OpenFastTraceScanner::scan(td.path(), &cfg).unwrap();
        assert_eq!(report.covered_requirements, 0);
        assert!(!report.is_compliant);
    }
}
