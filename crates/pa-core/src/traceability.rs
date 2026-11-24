use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet};
use std::fs;
use std::path::Path;

use crate::schema::TraceabilityConfig;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct RequirementCoverage {
    pub req_id: String,
    pub has_impl: bool,
    pub has_test: bool,
    pub impl_locations: Vec<String>,
    pub test_locations: Vec<String>,
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
        }
    }
}

pub struct OpenFastTraceScanner;

impl OpenFastTraceScanner {
    /// Scans a workspace for OpenFastTrace tags:
    /// - `req~<id>~<ver>` (Specification requirement)
    /// - `impl~<id>~<ver>` (Code implementation)
    /// - `utest~<id>~<ver>` or `vtest~<id>~<ver>` (Test cases)
    pub fn scan(root: &Path, config: &TraceabilityConfig) -> Result<TraceabilityReport> {
        let mut declared_reqs: HashSet<String> = HashSet::new();
        let mut impl_map: HashMap<String, Vec<String>> = HashMap::new();
        let mut test_map: HashMap<String, Vec<String>> = HashMap::new();

        Self::walk_and_scan(
            root,
            root,
            config,
            &mut declared_reqs,
            &mut impl_map,
            &mut test_map,
        )?;

        let mut details = HashMap::new();
        let mut missing_impl = Vec::new();
        let mut missing_tests = Vec::new();
        let mut covered_count = 0;

        for req_id in &declared_reqs {
            let impl_locs = impl_map.get(req_id).cloned().unwrap_or_default();
            let test_locs = test_map.get(req_id).cloned().unwrap_or_default();
            let has_impl = !impl_locs.is_empty();
            let has_test = !test_locs.is_empty();

            if !has_impl {
                missing_impl.push(req_id.clone());
            }
            if !has_test {
                missing_tests.push(req_id.clone());
            }

            let is_covered = if config.enforce_test_linkage {
                has_impl && has_test
            } else {
                has_impl
            };

            if is_covered {
                covered_count += 1;
            }

            details.insert(
                req_id.clone(),
                RequirementCoverage {
                    req_id: req_id.clone(),
                    has_impl,
                    has_test,
                    impl_locations: impl_locs,
                    test_locations: test_locs,
                },
            );
        }

        let total = declared_reqs.len();
        let coverage_pct = if total == 0 {
            100.0
        } else {
            (covered_count as f64 / total as f64) * 100.0
        };

        let is_compliant = coverage_pct >= config.min_coverage_pct;

        Ok(TraceabilityReport {
            engine: "openfasttrace".to_string(),
            total_requirements: total,
            covered_requirements: covered_count,
            missing_impl,
            missing_tests,
            coverage_pct,
            is_compliant,
            details,
        })
    }

    fn walk_and_scan(
        base: &Path,
        current: &Path,
        config: &TraceabilityConfig,
        reqs: &mut HashSet<String>,
        impls: &mut HashMap<String, Vec<String>>,
        tests: &mut HashMap<String, Vec<String>>,
    ) -> Result<()> {
        if !current.is_dir() {
            return Ok(());
        }

        for entry in fs::read_dir(current)?.filter_map(|e| e.ok()) {
            let path = entry.path();
            let name = path.file_name().and_then(|n| n.to_str()).unwrap_or("");

            // Skip hidden files/directories except .pa
            if name.starts_with('.') && name != ".pa" {
                continue;
            }

            // Inside .pa, only scan .pa/features
            if let Ok(rel) = path.strip_prefix(base) {
                if rel.starts_with(".pa")
                    && !rel.starts_with(".pa/features")
                    && rel != Path::new(".pa")
                {
                    continue;
                }
            }

            // Skip common build/cache directories
            if name == "target"
                || name == "node_modules"
                || name == ".venv"
                || name == "__pycache__"
                || name == "site"
            {
                continue;
            }

            if path.is_dir() {
                Self::walk_and_scan(base, &path, config, reqs, impls, tests)?;
            } else if path.is_file() {
                Self::scan_file(base, &path, config, reqs, impls, tests)?;
            }
        }

        Ok(())
    }

    fn scan_file(
        base: &Path,
        path: &Path,
        config: &TraceabilityConfig,
        reqs: &mut HashSet<String>,
        impls: &mut HashMap<String, Vec<String>>,
        tests: &mut HashMap<String, Vec<String>>,
    ) -> Result<()> {
        let ext = path.extension().and_then(|e| e.to_str()).unwrap_or("");
        let is_text = matches!(
            ext,
            "rs" | "py" | "md" | "toml" | "ts" | "js" | "swift" | "kt" | "java" | "sh" | "spec"
        );
        if !is_text {
            return Ok(());
        }

        let content = match fs::read_to_string(path) {
            Ok(c) => c,
            Err(_) => return Ok(()), // Skip non-UTF8 binary files safely
        };

        let rel_path = path.strip_prefix(base).unwrap_or(path);
        let rel_path_str = rel_path.display().to_string();
        let file_name = path.file_name().and_then(|n| n.to_str()).unwrap_or("");

        // Specification files define requirements (req~<id>).
        // Code/test files implement (impl~<id>) and test (utest~<id>, vtest~<id>) them.
        let is_spec = rel_path.starts_with(&config.spec_dir)
            || rel_path.starts_with("docs/specs")
            || rel_path.starts_with(".pa/features")
            || (ext == "md" && (rel_path.starts_with("docs") || file_name.starts_with("spec")));

        for (line_num, line) in content.lines().enumerate() {
            let loc = format!("{}:{}", rel_path_str, line_num + 1);

            if is_spec {
                // Requirements are declared only in specification documents
                for cap in extract_tag_ids(line, "req~") {
                    reqs.insert(cap);
                }
            }

            // Implementations and tests can be in any scanned file
            for cap in extract_tag_ids(line, "impl~") {
                impls.entry(cap).or_default().push(loc.clone());
            }

            // Scan for utest~<id> or vtest~<id>
            for cap in extract_tag_ids(line, "utest~") {
                tests.entry(cap).or_default().push(loc.clone());
            }
            for cap in extract_tag_ids(line, "vtest~") {
                tests.entry(cap).or_default().push(loc.clone());
            }
        }

        Ok(())
    }
}

fn extract_tag_ids(line: &str, prefix: &str) -> Vec<String> {
    let mut results = Vec::new();
    let mut search = line;

    while let Some(idx) = search.find(prefix) {
        let after = &search[idx + prefix.len()..];
        // Read until non-alphanumeric / non-hyphen / non-underscore or next ~ (version)
        let token_end = after
            .find(|c: char| !c.is_alphanumeric() && c != '-' && c != '_' && c != '~')
            .unwrap_or(after.len());
        let token = &after[..token_end];

        let id = if let Some(ver_idx) = token.find('~') {
            &token[..ver_idx]
        } else {
            token
        };

        if !id.is_empty() {
            results.push(id.to_string());
        }

        search = &after[token_end..];
    }

    results
}

pub fn evaluate_traceability_gate(
    root: &Path,
    config: &TraceabilityConfig,
) -> Result<TraceabilityReport> {
    match config.engine.to_lowercase().as_str() {
        "none" => Ok(TraceabilityReport::empty("none")),
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
    use tempfile::tempdir;

    #[test]
    fn test_extract_tag_ids() {
        let line = "// req~AUTH-01~1 and impl~AUTH-01~1 with utest~AUTH-01";
        assert_eq!(extract_tag_ids(line, "req~"), vec!["AUTH-01"]);
        assert_eq!(extract_tag_ids(line, "impl~"), vec!["AUTH-01"]);
        assert_eq!(extract_tag_ids(line, "utest~"), vec!["AUTH-01"]);
    }

    #[test]
    fn test_openfasttrace_scanner_full_compliance() {
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
            "// utest~AUTH-TOKEN~1\n#[test] fn test_rotate() {}\n",
        )
        .unwrap();

        let cfg = TraceabilityConfig {
            engine: "openfasttrace".to_string(),
            min_coverage_pct: 95.0,
            enforce_test_linkage: true,
            ..TraceabilityConfig::default()
        };

        let report = OpenFastTraceScanner::scan(td.path(), &cfg).unwrap();
        assert_eq!(report.total_requirements, 1);
        assert_eq!(report.covered_requirements, 1);
        assert_eq!(report.coverage_pct, 100.0);
        assert!(report.is_compliant);
    }

    #[test]
    fn test_openfasttrace_scanner_missing_test_fails_gate() {
        let td = tempdir().unwrap();
        let spec_file = td.path().join("spec.md");
        let src_file = td.path().join("auth.rs");

        fs::write(spec_file, "- req~AUTH-REVOKE~1: Revocation\n").unwrap();
        fs::write(src_file, "// impl~AUTH-REVOKE~1\nfn revoke() {}\n").unwrap();

        let cfg = TraceabilityConfig {
            engine: "openfasttrace".to_string(),
            min_coverage_pct: 95.0,
            enforce_test_linkage: true,
            ..TraceabilityConfig::default()
        };

        let report = OpenFastTraceScanner::scan(td.path(), &cfg).unwrap();
        assert_eq!(report.total_requirements, 1);
        assert_eq!(report.covered_requirements, 0);
        assert_eq!(report.coverage_pct, 0.0);
        assert!(!report.is_compliant);
        assert_eq!(report.missing_tests, vec!["AUTH-REVOKE"]);
    }
}
