use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use std::fs;
use std::path::Path;

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub enum TestOutcome {
    Passed,
    Failed(String),
    Error(String),
    Skipped(Option<String>),
}

impl TestOutcome {
    pub fn is_passed(&self) -> bool {
        matches!(self, TestOutcome::Passed)
    }

    pub fn is_failed(&self) -> bool {
        matches!(self, TestOutcome::Failed(_) | TestOutcome::Error(_))
    }

    pub fn is_skipped(&self) -> bool {
        matches!(self, TestOutcome::Skipped(_))
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct TestCase {
    pub name: String,
    pub classname: String,
    pub file: Option<String>,
    pub line: Option<usize>,
    pub time: f64,
    pub outcome: TestOutcome,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct TestSuite {
    pub name: String,
    pub tests: usize,
    pub failures: usize,
    pub errors: usize,
    pub skipped: usize,
    pub testcases: Vec<TestCase>,
}

#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
pub struct JUnitReport {
    pub suites: Vec<TestSuite>,
    pub total_tests: usize,
    pub passed_tests: usize,
    pub failed_tests: usize,
    pub skipped_tests: usize,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum TestExecutionStatus {
    Passed,
    Failed,
    Unexecuted,
}

impl JUnitReport {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn load_file(path: &Path) -> Result<Self> {
        let content = fs::read_to_string(path)
            .with_context(|| format!("Failed to read JUnit XML file at: {}", path.display()))?;
        Self::parse(&content)
    }

    pub fn load_multiple(paths: &[impl AsRef<Path>]) -> Result<Self> {
        let mut combined = JUnitReport::default();
        for p in paths {
            let p_ref = p.as_ref();
            if p_ref.exists() {
                let r = Self::load_file(p_ref)?;
                combined.merge(r);
            }
        }
        Ok(combined)
    }

    pub fn merge(&mut self, other: JUnitReport) {
        self.suites.extend(other.suites);
        self.total_tests += other.total_tests;
        self.passed_tests += other.passed_tests;
        self.failed_tests += other.failed_tests;
        self.skipped_tests += other.skipped_tests;
    }

    pub fn parse(xml_content: &str) -> Result<Self> {
        let mut report = JUnitReport::default();
        let mut current_suite: Option<TestSuite> = None;
        let mut current_case: Option<TestCase> = None;
        let mut current_tag_body = String::new();
        let mut in_outcome_tag: Option<String> = None;
        let mut outcome_message = String::new();

        let tokens = tokenize_xml(xml_content);
        for token in tokens {
            match token {
                XmlToken::StartTag {
                    name,
                    attrs,
                    self_closing,
                } => match name.as_str() {
                    "testsuite" => {
                        if let Some(s) = current_suite.take() {
                            report.add_suite(s);
                        }
                        let s_name = attrs.get("name").cloned().unwrap_or_default();
                        current_suite = Some(TestSuite {
                            name: s_name,
                            tests: attrs.get("tests").and_then(|v| v.parse().ok()).unwrap_or(0),
                            failures: attrs
                                .get("failures")
                                .and_then(|v| v.parse().ok())
                                .unwrap_or(0),
                            errors: attrs
                                .get("errors")
                                .and_then(|v| v.parse().ok())
                                .unwrap_or(0),
                            skipped: attrs
                                .get("skipped")
                                .and_then(|v| v.parse().ok())
                                .unwrap_or(0),
                            testcases: Vec::new(),
                        });
                    }
                    "testcase" => {
                        let tc_name = attrs.get("name").cloned().unwrap_or_default();
                        let tc_class = attrs.get("classname").cloned().unwrap_or_default();
                        let tc_file = attrs.get("file").cloned();
                        let tc_line = attrs.get("line").and_then(|v| v.parse().ok());
                        let tc_time = attrs
                            .get("time")
                            .and_then(|v| v.parse().ok())
                            .unwrap_or(0.0);

                        let tc = TestCase {
                            name: tc_name,
                            classname: tc_class,
                            file: tc_file,
                            line: tc_line,
                            time: tc_time,
                            outcome: TestOutcome::Passed,
                        };

                        if self_closing {
                            if let Some(ref mut suite) = current_suite {
                                suite.testcases.push(tc);
                            } else {
                                let anon = TestSuite {
                                    name: "default".to_string(),
                                    tests: 1,
                                    failures: 0,
                                    errors: 0,
                                    skipped: 0,
                                    testcases: vec![tc],
                                };
                                report.add_suite(anon);
                            }
                        } else {
                            current_case = Some(tc);
                        }
                    }
                    "failure" | "error" | "skipped" => {
                        if self_closing {
                            let msg = attrs.get("message").cloned();
                            if let Some(ref mut tc) = current_case {
                                match name.as_str() {
                                    "failure" => {
                                        tc.outcome = TestOutcome::Failed(msg.unwrap_or_default())
                                    }
                                    "error" => {
                                        tc.outcome = TestOutcome::Error(msg.unwrap_or_default())
                                    }
                                    "skipped" => tc.outcome = TestOutcome::Skipped(msg),
                                    _ => {}
                                }
                            }
                        } else {
                            in_outcome_tag = Some(name.clone());
                            outcome_message = attrs.get("message").cloned().unwrap_or_default();
                            current_tag_body.clear();
                        }
                    }
                    _ => {}
                },
                XmlToken::Text(text) => {
                    if in_outcome_tag.is_some() {
                        current_tag_body.push_str(&text);
                    }
                }
                XmlToken::EndTag { name } => match name.as_str() {
                    "failure" => {
                        if let Some(ref mut tc) = current_case {
                            let msg = if outcome_message.is_empty() {
                                current_tag_body.trim().to_string()
                            } else {
                                format!("{}: {}", outcome_message, current_tag_body.trim())
                            };
                            tc.outcome = TestOutcome::Failed(msg);
                        }
                        in_outcome_tag = None;
                        current_tag_body.clear();
                    }
                    "error" => {
                        if let Some(ref mut tc) = current_case {
                            let msg = if outcome_message.is_empty() {
                                current_tag_body.trim().to_string()
                            } else {
                                format!("{}: {}", outcome_message, current_tag_body.trim())
                            };
                            tc.outcome = TestOutcome::Error(msg);
                        }
                        in_outcome_tag = None;
                        current_tag_body.clear();
                    }
                    "skipped" => {
                        if let Some(ref mut tc) = current_case {
                            let msg = if outcome_message.is_empty() {
                                if current_tag_body.trim().is_empty() {
                                    None
                                } else {
                                    Some(current_tag_body.trim().to_string())
                                }
                            } else {
                                Some(outcome_message.clone())
                            };
                            tc.outcome = TestOutcome::Skipped(msg);
                        }
                        in_outcome_tag = None;
                        current_tag_body.clear();
                    }
                    "testcase" => {
                        if let Some(tc) = current_case.take() {
                            if let Some(ref mut suite) = current_suite {
                                suite.testcases.push(tc);
                            } else {
                                let anon = TestSuite {
                                    name: "default".to_string(),
                                    tests: 1,
                                    failures: 0,
                                    errors: 0,
                                    skipped: 0,
                                    testcases: vec![tc],
                                };
                                report.add_suite(anon);
                            }
                        }
                    }
                    "testsuite" => {
                        if let Some(s) = current_suite.take() {
                            report.add_suite(s);
                        }
                    }
                    _ => {}
                },
            }
        }

        if let Some(s) = current_suite.take() {
            report.add_suite(s);
        }

        Ok(report)
    }

    fn add_suite(&mut self, suite: TestSuite) {
        for tc in &suite.testcases {
            self.total_tests += 1;
            match &tc.outcome {
                TestOutcome::Passed => self.passed_tests += 1,
                TestOutcome::Failed(_) | TestOutcome::Error(_) => self.failed_tests += 1,
                TestOutcome::Skipped(_) => self.skipped_tests += 1,
            }
        }
        self.suites.push(suite);
    }

    /// Evaluates test execution status for a given requirement ID and its linked test locations/symbols.
    ///
    /// Algorithm:
    /// 1. Finds all test cases that match either:
    ///    - Exact requirement ID in testcase name or classname,
    ///    - Any extracted test symbol (e.g. function name `test_rotate`),
    ///    - File path hint matching testcase file/classname.
    /// 2. If no matching testcase is found or all matching tests are skipped, returns `Unexecuted`.
    /// 3. If ANY matched test has Failed or Error, returns `Failed`.
    /// 4. If at least one test matched and ALL matched tests Passed, returns `Passed`.
    pub fn evaluate_req_test_status(
        &self,
        req_id: &str,
        symbols: &[String],
        file_hints: &[String],
    ) -> TestExecutionStatus {
        let mut matched: Vec<&TestCase> = Vec::new();

        for suite in &self.suites {
            for tc in &suite.testcases {
                let mut is_match = false;

                // 1. Direct ID match
                let req_norm = req_id.replace('-', "_").to_lowercase();
                let tc_name_norm = tc.name.replace('-', "_").to_lowercase();
                let tc_class_norm = tc.classname.replace('-', "_").to_lowercase();

                if tc_name_norm.contains(&req_norm) || tc_class_norm.contains(&req_norm) {
                    is_match = true;
                }

                // 2. Extracted symbol match
                if !is_match {
                    for sym in symbols {
                        if !sym.is_empty() {
                            let sym_clean = sym.trim();
                            if tc.name == sym_clean
                                || tc.name.ends_with(&format!("::{}", sym_clean))
                                || tc.name.ends_with(&format!(".{}", sym_clean))
                            {
                                // If file hint is available, check for consistency
                                if !file_hints.is_empty() {
                                    let mut file_matches = false;
                                    for fh in file_hints {
                                        let fh_path = fh.split(':').next().unwrap_or(fh);
                                        if let Some(ref tc_file) = tc.file {
                                            if tc_file.ends_with(fh_path)
                                                || fh_path.ends_with(tc_file)
                                            {
                                                file_matches = true;
                                                break;
                                            }
                                        } else if tc.classname.contains(fh_path) {
                                            file_matches = true;
                                            break;
                                        }
                                    }
                                    if file_matches {
                                        is_match = true;
                                        break;
                                    }
                                } else {
                                    is_match = true;
                                    break;
                                }
                            }
                        }
                    }
                }

                if is_match {
                    matched.push(tc);
                }
            }
        }

        if matched.is_empty() {
            return TestExecutionStatus::Unexecuted;
        }

        let mut has_passed = false;
        for tc in matched {
            match &tc.outcome {
                TestOutcome::Failed(_) | TestOutcome::Error(_) => {
                    return TestExecutionStatus::Failed
                }
                TestOutcome::Passed => has_passed = true,
                TestOutcome::Skipped(_) => {}
            }
        }

        if has_passed {
            TestExecutionStatus::Passed
        } else {
            TestExecutionStatus::Unexecuted
        }
    }
}

enum XmlToken {
    StartTag {
        name: String,
        attrs: std::collections::HashMap<String, String>,
        self_closing: bool,
    },
    EndTag {
        name: String,
    },
    Text(String),
}

fn tokenize_xml(xml: &str) -> Vec<XmlToken> {
    let mut tokens = Vec::new();
    let mut chars = xml.char_indices().peekable();

    while let Some((idx, ch)) = chars.next() {
        if ch == '<' {
            // Check for comment <!-- ... -->
            if xml[idx..].starts_with("<!--") {
                if let Some(end_idx) = xml[idx..].find("-->") {
                    for _ in 0..end_idx + 2 {
                        chars.next();
                    }
                    continue;
                }
            }

            // Check for processing instruction <? ... ?>
            if xml[idx..].starts_with("<?") {
                if let Some(end_idx) = xml[idx..].find("?>") {
                    for _ in 0..end_idx + 1 {
                        chars.next();
                    }
                    continue;
                }
            }

            // Check for end tag </tagname>
            if xml[idx..].starts_with("</") {
                chars.next(); // consume '/'
                let mut tag_name = String::new();
                for (_, c) in chars.by_ref() {
                    if c == '>' {
                        break;
                    }
                    if !c.is_whitespace() {
                        tag_name.push(c);
                    }
                }
                tokens.push(XmlToken::EndTag { name: tag_name });
                continue;
            }

            // Start or self-closing tag
            let mut tag_content = String::new();
            for (_, c) in chars.by_ref() {
                if c == '>' {
                    break;
                }
                tag_content.push(c);
            }

            let trimmed = tag_content.trim();
            let self_closing = trimmed.ends_with('/');
            let content_no_slash = if self_closing {
                trimmed[..trimmed.len() - 1].trim()
            } else {
                trimmed
            };

            let mut parts = content_no_slash.split_whitespace();
            let tag_name = parts.next().unwrap_or("").to_string();
            let mut attrs = std::collections::HashMap::new();

            // Parse attributes: name="val" or name='val'
            let rest_attrs = &content_no_slash[tag_name.len()..].trim();
            let mut a_chars = rest_attrs.char_indices().peekable();
            while let Some((_, ac)) = a_chars.next() {
                if ac.is_alphanumeric() || ac == '_' || ac == '-' {
                    let mut a_name = String::new();
                    a_name.push(ac);
                    while let Some(&(_, nxt)) = a_chars.peek() {
                        if nxt == '=' || nxt.is_whitespace() {
                            break;
                        }
                        a_name.push(nxt);
                        a_chars.next();
                    }

                    // find '='
                    while let Some(&(_, nxt)) = a_chars.peek() {
                        if nxt == '=' {
                            a_chars.next();
                            break;
                        }
                        a_chars.next();
                    }

                    // find quote
                    let mut quote_char = None;
                    while let Some(&(_, nxt)) = a_chars.peek() {
                        if nxt == '"' || nxt == '\'' {
                            quote_char = Some(nxt);
                            a_chars.next();
                            break;
                        }
                        a_chars.next();
                    }

                    if let Some(qc) = quote_char {
                        let mut a_val = String::new();
                        for (_, val_c) in a_chars.by_ref() {
                            if val_c == qc {
                                break;
                            }
                            a_val.push(val_c);
                        }
                        attrs.insert(a_name, a_val);
                    }
                }
            }

            tokens.push(XmlToken::StartTag {
                name: tag_name,
                attrs,
                self_closing,
            });
        } else {
            let mut text = String::new();
            text.push(ch);
            while let Some(&(_, nxt)) = chars.peek() {
                if nxt == '<' {
                    break;
                }
                text.push(nxt);
                chars.next();
            }
            let trimmed_text = text.trim();
            if !trimmed_text.is_empty() {
                tokens.push(XmlToken::Text(trimmed_text.to_string()));
            }
        }
    }

    tokens
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_junit_xml_passed_and_failed() {
        let xml = r#"<?xml version="1.0" encoding="UTF-8"?>
<testsuites tests="3" failures="1" errors="0">
    <testsuite name="auth_tests" tests="3" failures="1" errors="0" skipped="1">
        <testcase name="test_token_rotate" classname="auth::tokens" time="0.04" file="tests/auth_test.rs" line="10"/>
        <testcase name="test_revoke_token" classname="auth::tokens" time="0.02" file="tests/auth_test.rs" line="25">
            <failure message="assertion failed: token.is_revoked()">Expected revoked token</failure>
        </testcase>
        <testcase name="test_sso_handshake" classname="auth::sso" time="0.00" file="tests/sso_test.rs">
            <skipped message="network disabled"/>
        </testcase>
    </testsuite>
</testsuites>"#;

        let report = JUnitReport::parse(xml).unwrap();
        assert_eq!(report.total_tests, 3);
        assert_eq!(report.passed_tests, 1);
        assert_eq!(report.failed_tests, 1);
        assert_eq!(report.skipped_tests, 1);

        assert_eq!(
            report.evaluate_req_test_status(
                "REQ-TOKEN-ROTATE",
                &["test_token_rotate".to_string()],
                &["tests/auth_test.rs".to_string()]
            ),
            TestExecutionStatus::Passed
        );

        assert_eq!(
            report.evaluate_req_test_status(
                "REQ-REVOKE",
                &["test_revoke_token".to_string()],
                &["tests/auth_test.rs".to_string()]
            ),
            TestExecutionStatus::Failed
        );

        assert_eq!(
            report.evaluate_req_test_status(
                "REQ-SSO",
                &["test_sso_handshake".to_string()],
                &["tests/sso_test.rs".to_string()]
            ),
            TestExecutionStatus::Unexecuted
        );

        assert_eq!(
            report.evaluate_req_test_status("REQ-NONEXISTENT", &["test_unknown".to_string()], &[]),
            TestExecutionStatus::Unexecuted
        );
    }

    #[test]
    fn test_parse_junit_xml_direct_req_id_in_name() {
        let xml = r#"<testsuite name="specs">
    <testcase name="test_req_auth_token_rotation" classname="suite" time="0.01"/>
</testsuite>"#;

        let report = JUnitReport::parse(xml).unwrap();
        assert_eq!(report.total_tests, 1);
        assert_eq!(report.passed_tests, 1);

        assert_eq!(
            report.evaluate_req_test_status("AUTH-TOKEN-ROTATION", &[], &[]),
            TestExecutionStatus::Passed
        );
    }
}
