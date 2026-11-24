use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet};
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

use super::coverage::CoverageReport;
use super::junit::{JUnitReport, TestExecutionStatus};
use super::{RequirementCoverage, TraceabilityReport};
use crate::schema::TraceabilityConfig;

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct StrictDocRequirement {
    pub uid: String,
    pub title: String,
    pub statement: String,
    pub parent_kr: Option<String>,
    pub relations: Vec<(String, String)>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct TaggedLocation {
    pub location: String,
    pub file_path: String,
    pub line_num: usize,
    pub symbol: Option<String>,
    pub is_test: bool,
}

pub struct StrictDocEngine;

impl StrictDocEngine {
    /// Scans workspace using StrictDoc conventions:
    /// - `.sdoc` documents in `docs/specs` or configured `spec_dir`
    /// - Source code `@relation(REQ-..., scope=...)` annotations
    /// - Cross-references JUnit XML and coverage reports
    pub fn scan(root: &Path, config: &TraceabilityConfig) -> Result<TraceabilityReport> {
        let mut req_map: HashMap<String, StrictDocRequirement> = HashMap::new();
        let mut impl_map: HashMap<String, Vec<TaggedLocation>> = HashMap::new();
        let mut test_map: HashMap<String, Vec<TaggedLocation>> = HashMap::new();

        // 1. Scan for .sdoc requirement definitions
        let spec_dir = root.join(&config.spec_dir);
        if spec_dir.is_dir() {
            Self::scan_sdoc_dir(&spec_dir, &mut req_map)?;
        }
        // Also scan docs/specs if different
        let default_specs = root.join("docs/specs");
        if default_specs.is_dir() && default_specs != spec_dir {
            Self::scan_sdoc_dir(&default_specs, &mut req_map)?;
        }

        // 2. Scan workspace files for @relation annotations
        Self::walk_and_scan(root, root, &mut impl_map, &mut test_map)?;

        // 3. Load JUnit XML test reports if present or required
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

        // 4. Load coverage report if present or required
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

        // 5. Build requirement coverage matrix
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

        let declared_req_ids: HashSet<String> = req_map.keys().cloned().collect();

        // Check for orphaned annotations (linking to non-existent UIDs)
        for req_id in impl_map.keys().chain(test_map.keys()) {
            if !declared_req_ids.contains(req_id) && !orphaned_links.contains(req_id) {
                orphaned_links.push(req_id.clone());
            }
        }

        for req_id in req_map.keys() {
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
                // If JUnit is not available and not strictly required, assume linked test covers tag
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

        let total = req_map.len();
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

        // 6. Optional CLI HTML/JSON export
        let report_artifact = Self::try_export_strictdoc_cli(root, config)?;

        Ok(TraceabilityReport {
            engine: "strictdoc".to_string(),
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
            report_artifact,
        })
    }

    pub fn scan_sdoc_dir(
        dir: &Path,
        req_map: &mut HashMap<String, StrictDocRequirement>,
    ) -> Result<()> {
        for entry in fs::read_dir(dir)?.flatten() {
            let path = entry.path();
            if path.is_file() && path.extension().and_then(|e| e.to_str()) == Some("sdoc") {
                let content = fs::read_to_string(&path)
                    .with_context(|| format!("Failed to read .sdoc file: {}", path.display()))?;
                for req in Self::parse_sdoc(&content) {
                    req_map.insert(req.uid.clone(), req);
                }
            } else if path.is_dir() {
                Self::scan_sdoc_dir(&path, req_map)?;
            }
        }
        Ok(())
    }

    /// Parses StrictDoc `.sdoc` documents into `StrictDocRequirement` definitions.
    pub fn parse_sdoc(content: &str) -> Vec<StrictDocRequirement> {
        let mut reqs = Vec::new();
        let mut in_req = false;
        let mut cur_uid = String::new();
        let mut cur_title = String::new();
        let mut cur_statement = String::new();
        let mut cur_parent_kr: Option<String> = None;
        let mut cur_relations = Vec::new();
        let mut in_relations = false;
        let mut cur_rel_type = String::new();

        let flush_req = |reqs: &mut Vec<StrictDocRequirement>,
                         uid: &mut String,
                         title: &mut String,
                         statement: &mut String,
                         parent_kr: &mut Option<String>,
                         relations: &mut Vec<(String, String)>| {
            if !uid.is_empty() {
                reqs.push(StrictDocRequirement {
                    uid: uid.clone(),
                    title: title.clone(),
                    statement: statement.trim().to_string(),
                    parent_kr: parent_kr.clone(),
                    relations: std::mem::take(relations),
                });
            }
            uid.clear();
            title.clear();
            statement.clear();
            *parent_kr = None;
        };

        for line in content.lines() {
            let trimmed = line.trim();

            if trimmed == "[REQUIREMENT]" {
                if in_req {
                    flush_req(
                        &mut reqs,
                        &mut cur_uid,
                        &mut cur_title,
                        &mut cur_statement,
                        &mut cur_parent_kr,
                        &mut cur_relations,
                    );
                }
                in_req = true;
                in_relations = false;
                continue;
            }

            if in_req && (trimmed.starts_with('[') && trimmed.ends_with(']')) {
                // Another section or block started
                flush_req(
                    &mut reqs,
                    &mut cur_uid,
                    &mut cur_title,
                    &mut cur_statement,
                    &mut cur_parent_kr,
                    &mut cur_relations,
                );
                in_req = false;
                in_relations = false;
                continue;
            }

            if in_req {
                if let Some(rest) = trimmed.strip_prefix("UID:") {
                    cur_uid = rest.trim().to_string();
                    in_relations = false;
                } else if let Some(rest) = trimmed.strip_prefix("TITLE:") {
                    cur_title = rest.trim().to_string();
                    in_relations = false;
                } else if let Some(rest) = trimmed.strip_prefix("STATEMENT:") {
                    cur_statement.push_str(rest.trim());
                    cur_statement.push('\n');
                    in_relations = false;
                } else if trimmed.starts_with("RELATIONS:") {
                    in_relations = true;
                } else if in_relations {
                    if let Some(rest) = trimmed.strip_prefix("- TYPE:") {
                        cur_rel_type = rest.trim().to_string();
                    } else if let Some(rest) = trimmed.strip_prefix("VALUE:") {
                        let val = rest.trim().to_string();
                        if cur_rel_type.eq_ignore_ascii_case("Parent")
                            && (val.starts_with("KR-") || val.starts_with("OKR-"))
                        {
                            cur_parent_kr = Some(val.clone());
                        }
                        cur_relations.push((cur_rel_type.clone(), val));
                    }
                } else if !trimmed.is_empty() && !cur_statement.is_empty() && !trimmed.contains(':')
                {
                    // Continuing statement
                    cur_statement.push_str(trimmed);
                    cur_statement.push('\n');
                }
            }
        }

        if in_req {
            flush_req(
                &mut reqs,
                &mut cur_uid,
                &mut cur_title,
                &mut cur_statement,
                &mut cur_parent_kr,
                &mut cur_relations,
            );
        }

        reqs
    }

    fn walk_and_scan(
        base: &Path,
        current: &Path,
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
                Self::walk_and_scan(base, &path, impls, tests)?;
            } else if path.is_file() {
                Self::scan_code_file(base, &path, impls, tests)?;
            }
        }

        Ok(())
    }

    fn scan_code_file(
        base: &Path,
        path: &Path,
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

        let is_test_file = rel_path_str.contains("tests/")
            || rel_path_str.contains("test/")
            || rel_path_str.contains("_test.")
            || rel_path_str.contains("test_")
            || rel_path_str.ends_with(".spec.ts")
            || rel_path_str.ends_with(".spec.js");

        let lines: Vec<&str> = content.lines().collect();
        for (line_idx, line) in lines.iter().enumerate() {
            let tags = extract_relation_tags(line);
            if tags.is_empty() {
                continue;
            }

            // Extract adjacent symbol on the next 1-5 lines
            let symbol = extract_adjacent_symbol(&lines, line_idx + 1);

            for tag in tags {
                let is_test = tag.is_explicit_test || is_test_file;
                let loc = TaggedLocation {
                    location: format!("{}:{}", rel_path_str, line_idx + 1),
                    file_path: rel_path_str.clone(),
                    line_num: line_idx + 1,
                    symbol: symbol.clone(),
                    is_test,
                };

                if is_test {
                    tests.entry(tag.req_id).or_default().push(loc);
                } else {
                    impls.entry(tag.req_id).or_default().push(loc);
                }
            }
        }

        Ok(())
    }

    fn try_export_strictdoc_cli(
        root: &Path,
        config: &TraceabilityConfig,
    ) -> Result<Option<String>> {
        let strictdoc_bin = Command::new("strictdoc").arg("--version").output();

        match strictdoc_bin {
            Ok(out) if out.status.success() => {
                let out_dir = root.join(".pa/reports/strictdoc");
                let _ = fs::create_dir_all(&out_dir);

                let status = Command::new("strictdoc")
                    .args([
                        "export",
                        config.spec_dir.to_str().unwrap_or("docs/specs"),
                        "--output-dir",
                        out_dir.to_str().unwrap_or(".pa/reports/strictdoc"),
                        "--formats=html,json",
                    ])
                    .current_dir(root)
                    .status();

                match status {
                    Ok(s) if s.success() => {
                        Ok(Some(".pa/reports/strictdoc/index.html".to_string()))
                    }
                    _ => Ok(None),
                }
            }
            _ => {
                if config.on_missing_tool.eq_ignore_ascii_case("block") {
                    anyhow::bail!("strictdoc CLI is not available in PATH and on_missing_tool is set to 'block'");
                }
                Ok(None)
            }
        }
    }
}

pub struct ParsedRelationTag {
    pub req_id: String,
    pub is_explicit_test: bool,
}

pub fn extract_relation_tags(line: &str) -> Vec<ParsedRelationTag> {
    let mut results = Vec::new();
    let mut search = line;

    while let Some(idx) = search.find("@relation(") {
        let after = &search[idx + "@relation(".len()..];
        if let Some(close_idx) = after.find(')') {
            let inner = &after[..close_idx];
            let parts: Vec<&str> = inner.split(',').map(|s| s.trim()).collect();
            if let Some(first) = parts.first() {
                let req_id = first
                    .trim_matches(|c: char| c == '"' || c == '\'')
                    .to_string();
                if !req_id.is_empty() {
                    let mut is_explicit_test = false;
                    for p in &parts[1..] {
                        let lower = p.to_lowercase();
                        if lower.contains("test") || lower.contains("verif") {
                            is_explicit_test = true;
                        }
                    }
                    results.push(ParsedRelationTag {
                        req_id,
                        is_explicit_test,
                    });
                }
            }
            search = &after[close_idx + 1..];
        } else {
            break;
        }
    }

    results
}

pub fn extract_adjacent_symbol(lines: &[&str], start_idx: usize) -> Option<String> {
    for line in lines.iter().skip(start_idx).take(5) {
        let trimmed = line.trim();
        if trimmed.is_empty()
            || trimmed.starts_with("//")
            || trimmed.starts_with('#')
            || trimmed.starts_with('*')
        {
            continue;
        }

        // Rust: fn test_name / pub fn test_name / async fn test_name
        if let Some(fn_idx) = trimmed.find("fn ") {
            let after_fn = &trimmed[fn_idx + 3..];
            let name_end = after_fn
                .find(|c: char| !c.is_alphanumeric() && c != '_')
                .unwrap_or(after_fn.len());
            let sym = &after_fn[..name_end];
            if !sym.is_empty() {
                return Some(sym.to_string());
            }
        }

        // Python: def test_name(
        if let Some(def_idx) = trimmed.find("def ") {
            let after_def = &trimmed[def_idx + 4..];
            let name_end = after_def
                .find(|c: char| !c.is_alphanumeric() && c != '_')
                .unwrap_or(after_def.len());
            let sym = &after_def[..name_end];
            if !sym.is_empty() {
                return Some(sym.to_string());
            }
        }

        // JS/TS: test('test_name', ...) or it('test_name', ...)
        if trimmed.starts_with("test(") || trimmed.starts_with("it(") {
            let quote = if trimmed.contains('"') {
                Some('"')
            } else if trimmed.contains('\'') {
                Some('\'')
            } else {
                None
            };
            if let Some(q) = quote {
                if let Some(first_q) = trimmed.find(q) {
                    let after = &trimmed[first_q + 1..];
                    if let Some(second_q) = after.find(q) {
                        return Some(after[..second_q].to_string());
                    }
                }
            }
        }
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn test_parse_sdoc() {
        let sdoc = r#"[DOCUMENT]
TITLE: Test Spec

[REQUIREMENT]
UID: REQ-001
TITLE: First Req
STATEMENT: The system shall do foo.
RELATIONS:
- TYPE: Parent
  VALUE: KR-01

[REQUIREMENT]
UID: REQ-002
TITLE: Second Req
STATEMENT: The system shall do bar.
RELATIONS:
- TYPE: Parent
  VALUE: KR-02
"#;

        let reqs = StrictDocEngine::parse_sdoc(sdoc);
        assert_eq!(reqs.len(), 2);
        assert_eq!(reqs[0].uid, "REQ-001");
        assert_eq!(reqs[0].title, "First Req");
        assert_eq!(reqs[0].parent_kr, Some("KR-01".to_string()));
        assert_eq!(reqs[1].uid, "REQ-002");
    }

    #[test]
    fn test_extract_relation_tags() {
        let line = "// @relation(REQ-001, scope=function) and @relation(REQ-002, type=Verifies)";
        let tags = extract_relation_tags(line);
        assert_eq!(tags.len(), 2);
        assert_eq!(tags[0].req_id, "REQ-001");
        assert!(!tags[0].is_explicit_test);
        assert_eq!(tags[1].req_id, "REQ-002");
        assert!(tags[1].is_explicit_test);
    }

    #[test]
    fn test_extract_adjacent_symbol() {
        let lines = vec![
            "#[test]",
            "pub fn test_token_rotation() {",
            "    assert!(true);",
            "}",
        ];
        let sym = extract_adjacent_symbol(&lines, 0);
        assert_eq!(sym, Some("test_token_rotation".to_string()));
    }

    #[test]
    fn test_strictdoc_engine_scan_and_execution_verification() {
        let td = tempdir().unwrap();
        let specs_dir = td.path().join("docs/specs");
        fs::create_dir_all(&specs_dir).unwrap();

        let sdoc_content = r#"[REQUIREMENT]
UID: REQ-AUTH-01
TITLE: Auth Token
STATEMENT: Enforce auth token.
RELATIONS:
- TYPE: Parent
  VALUE: KR-AUTH-01
"#;
        fs::write(specs_dir.join("auth.sdoc"), sdoc_content).unwrap();

        let src_dir = td.path().join("src");
        fs::create_dir_all(&src_dir).unwrap();
        fs::write(
            src_dir.join("auth.rs"),
            "// @relation(REQ-AUTH-01, scope=function)\npub fn auth() {}\n",
        )
        .unwrap();

        let tests_dir = td.path().join("tests");
        fs::create_dir_all(&tests_dir).unwrap();
        fs::write(
            tests_dir.join("auth_test.rs"),
            "// @relation(REQ-AUTH-01, scope=function)\n#[test]\nfn test_auth() {}\n",
        )
        .unwrap();

        let reports_dir = td.path().join(".pa/reports");
        fs::create_dir_all(&reports_dir).unwrap();
        let junit_xml = r#"<testsuite name="auth">
    <testcase name="test_auth" classname="auth_test" file="tests/auth_test.rs" time="0.01"/>
</testsuite>"#;
        fs::write(reports_dir.join("junit.xml"), junit_xml).unwrap();

        let cfg = TraceabilityConfig {
            engine: "strictdoc".to_string(),
            spec_dir: PathBuf::from("docs/specs"),
            min_coverage_pct: 95.0,
            enforce_test_linkage: true,
            require_test_execution: true,
            junit_report_paths: vec![".pa/reports/junit.xml".to_string()],
            ..Default::default()
        };

        let report = StrictDocEngine::scan(td.path(), &cfg).unwrap();
        assert_eq!(report.total_requirements, 1);
        assert_eq!(report.covered_requirements, 1);
        assert_eq!(report.tests_passed, 1);
        assert_eq!(report.tests_failed, 0);
        assert_eq!(report.tests_unexecuted, 0);
        assert!(report.is_compliant);
    }
}
