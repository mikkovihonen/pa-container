use anyhow::Result;
use std::collections::{HashMap, HashSet};
use std::fs;
use std::path::{Path, PathBuf};

use super::coverage::CoverageReport;
use super::junit::{JUnitReport, TestExecutionStatus};
use super::strictdoc::{extract_adjacent_symbol, TaggedLocation};
use super::{RequirementCoverage, TraceabilityReport};
use crate::schema::TraceabilityConfig;

pub struct OpenFastTraceScanner;

impl OpenFastTraceScanner {
    /// Scans a workspace for OpenFastTrace tags:
    /// - `req~<id>~<ver>` (Specification requirement)
    /// - `impl~<id>~<ver>` (Code implementation)
    /// - `utest~<id>~<ver>` or `vtest~<id>~<ver>` (Test cases)
    ///
    /// Cross-references JUnit XML test execution results and code coverage.
    pub fn scan(root: &Path, config: &TraceabilityConfig) -> Result<TraceabilityReport> {
        let mut declared_reqs: HashSet<String> = HashSet::new();
        let mut impl_map: HashMap<String, Vec<TaggedLocation>> = HashMap::new();
        let mut test_map: HashMap<String, Vec<TaggedLocation>> = HashMap::new();

        Self::walk_and_scan(
            root,
            root,
            config,
            &mut declared_reqs,
            &mut impl_map,
            &mut test_map,
        )?;

        // Load JUnit XML reports if present or required
        let mut junit_report = JUnitReport::new();
        let mut junit_found = false;
        for rel_p in &config.junit_report_paths {
            let p = root.join(rel_p);
            if p.is_file() {
                if let Ok(rep) = JUnitReport::load_file(&p) {
                    junit_report.merge(rep);
                    junit_found = true;
                }
            }
        }

        if config.require_test_execution && !junit_found {
            anyhow::bail!(
                "Traceability test execution verification required (`require_test_execution = true`), \
                 but no JUnit report was found at configured paths: {:?}",
                config.junit_report_paths
            );
        }

        // Load coverage report if present or required
        let mut coverage_report: Option<CoverageReport> = None;
        if let Some(ref cov_path_str) = config.coverage_report_path {
            let cov_p = root.join(cov_path_str);
            if cov_p.is_file() {
                coverage_report = CoverageReport::load_file(&cov_p).ok();
            } else if config.min_line_coverage_pct.is_some() {
                if config.on_missing_tool.eq_ignore_ascii_case("skip") {
                    eprintln!(
                        "[WARN] Coverage report not found at {} (skipped due to on_missing_tool = 'skip')",
                        cov_p.display()
                    );
                } else {
                    anyhow::bail!(
                        "Traceability line coverage threshold configured (`min_line_coverage_pct`), \
                         but coverage report file was not found at: {}",
                        cov_p.display()
                    );
                }
            }
        }

        let mut details = HashMap::new();
        let mut missing_impl = Vec::new();
        let mut missing_tests = Vec::new();
        let mut failing_req_ids = Vec::new();
        let mut unexecuted_req_ids = Vec::new();
        let mut uncovered_req_ids = Vec::new();
        let mut orphaned_links = Vec::new();
        let mut covered_count = 0;
        let mut tests_passed_count = 0;
        let mut tests_failed_count = 0;
        let mut tests_unexecuted_count = 0;

        // Check for orphaned annotations (linking to undeclared req IDs)
        for req_id in impl_map.keys().chain(test_map.keys()) {
            if !declared_reqs.contains(req_id) && !orphaned_links.contains(req_id) {
                orphaned_links.push(req_id.clone());
            }
        }

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

            // Test execution evaluation
            let (test_passed, test_executed) = if junit_found && has_test {
                let symbols: Vec<String> =
                    test_locs.iter().filter_map(|l| l.symbol.clone()).collect();
                let files: Vec<String> = test_locs.iter().map(|l| l.file_path.clone()).collect();

                match junit_report.evaluate_req_test_status(req_id, &symbols, &files) {
                    TestExecutionStatus::Passed => {
                        tests_passed_count += 1;
                        (true, true)
                    }
                    TestExecutionStatus::Failed => {
                        tests_failed_count += 1;
                        failing_req_ids.push(req_id.clone());
                        (false, true)
                    }
                    TestExecutionStatus::Unexecuted => {
                        tests_unexecuted_count += 1;
                        unexecuted_req_ids.push(req_id.clone());
                        (false, false)
                    }
                }
            } else if has_test {
                (true, true)
            } else {
                (false, false)
            };

            // Compute line coverage for linked implementation files
            let req_line_cov = if let Some(ref cov_rep) = coverage_report {
                let files: Vec<PathBuf> = impl_locs
                    .iter()
                    .map(|l| PathBuf::from(&l.file_path))
                    .collect();
                cov_rep.compute_coverage_for_files(&files)
            } else {
                None
            };

            let line_cov_ok = match (config.min_line_coverage_pct, req_line_cov) {
                (Some(min_pct), Some(actual_pct)) => actual_pct >= min_pct,
                (Some(_), None) => {
                    // If coverage report was missing and skipped via on_missing_tool = 'skip', do not fail gate
                    coverage_report.is_none() && config.on_missing_tool.eq_ignore_ascii_case("skip")
                }
                (None, _) => true,
            };

            let is_covered = if config.require_test_execution {
                has_impl && has_test && test_passed && line_cov_ok
            } else if config.enforce_test_linkage {
                has_impl && has_test && line_cov_ok
            } else {
                has_impl && line_cov_ok
            };

            if is_covered {
                covered_count += 1;
            } else {
                uncovered_req_ids.push(req_id.clone());
            }

            details.insert(
                req_id.clone(),
                RequirementCoverage {
                    req_id: req_id.clone(),
                    has_impl,
                    has_test,
                    impl_locations: impl_locs.into_iter().map(|l| l.location).collect(),
                    test_locations: test_locs.into_iter().map(|l| l.location).collect(),
                    test_passed,
                    test_executed,
                    line_coverage_pct: req_line_cov,
                },
            );
        }

        let total = declared_reqs.len();
        let coverage_pct = if total == 0 {
            100.0
        } else {
            (covered_count as f64 / total as f64) * 100.0
        };

        let overall_line_cov = coverage_report
            .as_ref()
            .map(|c| c.overall_line_coverage_pct);
        let mut is_compliant = coverage_pct >= config.min_coverage_pct;

        if config.require_test_execution
            && (!failing_req_ids.is_empty() || !unexecuted_req_ids.is_empty())
        {
            is_compliant = false;
        }

        if let (Some(min_cov), Some(actual_cov)) = (config.min_line_coverage_pct, overall_line_cov)
        {
            if actual_cov < min_cov {
                is_compliant = false;
            }
        }

        Ok(TraceabilityReport {
            engine: "openfasttrace".to_string(),
            total_requirements: total,
            covered_requirements: covered_count,
            missing_impl,
            missing_tests,
            coverage_pct,
            is_compliant,
            details,
            tests_passed: tests_passed_count,
            tests_failed: tests_failed_count,
            tests_unexecuted: tests_unexecuted_count,
            line_coverage_pct: overall_line_cov,
            uncovered_req_ids,
            failing_req_ids,
            unexecuted_req_ids,
            orphaned_links,
            report_artifact: None,
        })
    }

    fn walk_and_scan(
        base: &Path,
        current: &Path,
        config: &TraceabilityConfig,
        reqs: &mut HashSet<String>,
        impls: &mut HashMap<String, Vec<TaggedLocation>>,
        tests: &mut HashMap<String, Vec<TaggedLocation>>,
    ) -> Result<()> {
        if !current.is_dir() {
            return Ok(());
        }

        for entry in fs::read_dir(current)?.flatten() {
            let path = entry.path();
            let name = path.file_name().and_then(|n| n.to_str()).unwrap_or("");

            if name.starts_with('.') && name != ".pa" {
                continue;
            }

            if let Ok(rel) = path.strip_prefix(base) {
                if rel.starts_with(".pa")
                    && !rel.starts_with(".pa/features")
                    && rel != Path::new(".pa")
                {
                    continue;
                }
            }

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
        impls: &mut HashMap<String, Vec<TaggedLocation>>,
        tests: &mut HashMap<String, Vec<TaggedLocation>>,
    ) -> Result<()> {
        let ext = path.extension().and_then(|e| e.to_str()).unwrap_or("");
        let is_text = matches!(
            ext,
            "rs" | "py"
                | "md"
                | "toml"
                | "ts"
                | "js"
                | "swift"
                | "kt"
                | "java"
                | "c"
                | "cpp"
                | "h"
                | "hpp"
                | "sh"
                | "spec"
        );
        if !is_text {
            return Ok(());
        }

        let content = match fs::read_to_string(path) {
            Ok(c) => c,
            Err(_) => return Ok(()),
        };

        let rel_path = path.strip_prefix(base).unwrap_or(path);
        let rel_path_str = rel_path.display().to_string();
        let file_name = path.file_name().and_then(|n| n.to_str()).unwrap_or("");

        let is_spec = rel_path.starts_with(&config.spec_dir)
            || rel_path.starts_with("docs/specs")
            || rel_path.starts_with(".pa/features")
            || (ext == "md" && (rel_path.starts_with("docs") || file_name.starts_with("spec")));

        let lines: Vec<&str> = content.lines().collect();

        for (line_num, line) in lines.iter().enumerate() {
            let loc_str = format!("{}:{}", rel_path_str, line_num + 1);

            if is_spec {
                for cap in extract_tag_ids(line, "req~") {
                    reqs.insert(cap);
                }
            }

            for cap in extract_tag_ids(line, "impl~") {
                impls.entry(cap).or_default().push(TaggedLocation {
                    location: loc_str.clone(),
                    file_path: rel_path_str.clone(),
                    line_num: line_num + 1,
                    symbol: None,
                    is_test: false,
                });
            }

            let mut test_caps = extract_tag_ids(line, "utest~");
            test_caps.extend(extract_tag_ids(line, "vtest~"));

            if !test_caps.is_empty() {
                let symbol = extract_adjacent_symbol(&lines, line_num + 1);
                for cap in test_caps {
                    tests.entry(cap).or_default().push(TaggedLocation {
                        location: loc_str.clone(),
                        file_path: rel_path_str.clone(),
                        line_num: line_num + 1,
                        symbol: symbol.clone(),
                        is_test: true,
                    });
                }
            }
        }

        Ok(())
    }
}

pub fn extract_tag_ids(line: &str, prefix: &str) -> Vec<String> {
    let mut results = Vec::new();
    let mut search = line;

    while let Some(idx) = search.find(prefix) {
        let after = &search[idx + prefix.len()..];
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
