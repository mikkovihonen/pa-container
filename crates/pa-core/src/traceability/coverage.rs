use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct FileCoverage {
    pub file_path: PathBuf,
    pub lines_found: usize,
    pub lines_hit: usize,
    pub line_coverage_pct: f64,
}

#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
pub struct CoverageReport {
    pub files: HashMap<PathBuf, FileCoverage>,
    pub total_lines_found: usize,
    pub total_lines_hit: usize,
    pub overall_line_coverage_pct: f64,
}

impl CoverageReport {
    pub fn load_file(path: &Path) -> Result<Self> {
        let content = fs::read_to_string(path).with_context(|| {
            format!("Failed to read coverage report file at: {}", path.display())
        })?;
        Self::parse(&content)
    }

    pub fn parse(content: &str) -> Result<Self> {
        let trimmed = content.trim();
        if trimmed.starts_with('{') {
            Self::parse_json(trimmed)
        } else {
            Self::parse_lcov(trimmed)
        }
    }

    pub fn parse_lcov(content: &str) -> Result<Self> {
        let mut files = HashMap::new();
        let mut cur_file: Option<PathBuf> = None;
        let mut cur_found: usize = 0;
        let mut cur_hit: usize = 0;
        let mut total_found: usize = 0;
        let mut total_hit: usize = 0;

        for line in content.lines() {
            let line = line.trim();
            if let Some(rest) = line.strip_prefix("SF:") {
                cur_file = Some(PathBuf::from(rest.trim()));
                cur_found = 0;
                cur_hit = 0;
            } else if let Some(rest) = line.strip_prefix("DA:") {
                let parts: Vec<&str> = rest.split(',').collect();
                if parts.len() >= 2 {
                    cur_found += 1;
                    if let Ok(count) = parts[1].trim().parse::<usize>() {
                        if count > 0 {
                            cur_hit += 1;
                        }
                    }
                }
            } else if let Some(rest) = line.strip_prefix("LF:") {
                if let Ok(v) = rest.trim().parse::<usize>() {
                    cur_found = v;
                }
            } else if let Some(rest) = line.strip_prefix("LH:") {
                if let Ok(v) = rest.trim().parse::<usize>() {
                    cur_hit = v;
                }
            } else if line == "end_of_record" {
                if let Some(file_path) = cur_file.take() {
                    let pct = if cur_found == 0 {
                        100.0
                    } else {
                        (cur_hit as f64 / cur_found as f64) * 100.0
                    };
                    total_found += cur_found;
                    total_hit += cur_hit;

                    files.insert(
                        file_path.clone(),
                        FileCoverage {
                            file_path,
                            lines_found: cur_found,
                            lines_hit: cur_hit,
                            line_coverage_pct: pct,
                        },
                    );
                }
            }
        }

        let overall_pct = if total_found == 0 {
            100.0
        } else {
            (total_hit as f64 / total_found as f64) * 100.0
        };

        Ok(CoverageReport {
            files,
            total_lines_found: total_found,
            total_lines_hit: total_hit,
            overall_line_coverage_pct: overall_pct,
        })
    }

    pub fn parse_json(content: &str) -> Result<Self> {
        let val: serde_json::Value =
            serde_json::from_str(content).context("Failed to parse coverage JSON report")?;

        let mut files = HashMap::new();
        let mut total_found: usize = 0;
        let mut total_hit: usize = 0;

        // Check if llvm-cov JSON: {"data": [{"files": [...]}]}
        if let Some(data_arr) = val.get("data").and_then(|v| v.as_array()) {
            for entry in data_arr {
                if let Some(files_arr) = entry.get("files").and_then(|v| v.as_array()) {
                    for f in files_arr {
                        let filename = f.get("filename").and_then(|v| v.as_str()).unwrap_or("");
                        if filename.is_empty() {
                            continue;
                        }

                        let (found, hit, pct) = if let Some(summary) =
                            f.get("summary").and_then(|v| v.get("lines"))
                        {
                            let count =
                                summary.get("count").and_then(|v| v.as_u64()).unwrap_or(0) as usize;
                            let covered =
                                summary.get("covered").and_then(|v| v.as_u64()).unwrap_or(0)
                                    as usize;
                            let p = summary
                                .get("percent")
                                .and_then(|v| v.as_f64())
                                .unwrap_or_else(|| {
                                    if count == 0 {
                                        100.0
                                    } else {
                                        (covered as f64 / count as f64) * 100.0
                                    }
                                });
                            (count, covered, p)
                        } else {
                            (0, 0, 100.0)
                        };

                        total_found += found;
                        total_hit += hit;

                        let pbuf = PathBuf::from(filename);
                        files.insert(
                            pbuf.clone(),
                            FileCoverage {
                                file_path: pbuf,
                                lines_found: found,
                                lines_hit: hit,
                                line_coverage_pct: pct,
                            },
                        );
                    }
                }
            }
        } else if let Some(files_arr) = val.get("files").and_then(|v| v.as_array()) {
            // Check if gcov JSON: {"files": [{"file": "...", "lines": [{"line_number": 1, "count": 2}]}]}
            for f in files_arr {
                let filename = f.get("file").and_then(|v| v.as_str()).unwrap_or("");
                if filename.is_empty() {
                    continue;
                }

                let mut found = 0;
                let mut hit = 0;
                if let Some(lines) = f.get("lines").and_then(|v| v.as_array()) {
                    for l in lines {
                        found += 1;
                        if let Some(c) = l.get("count").and_then(|v| v.as_u64()) {
                            if c > 0 {
                                hit += 1;
                            }
                        }
                    }
                }

                let pct = if found == 0 {
                    100.0
                } else {
                    (hit as f64 / found as f64) * 100.0
                };
                total_found += found;
                total_hit += hit;

                let pbuf = PathBuf::from(filename);
                files.insert(
                    pbuf.clone(),
                    FileCoverage {
                        file_path: pbuf,
                        lines_found: found,
                        lines_hit: hit,
                        line_coverage_pct: pct,
                    },
                );
            }
        }

        let overall_pct = if total_found == 0 {
            100.0
        } else {
            (total_hit as f64 / total_found as f64) * 100.0
        };

        Ok(CoverageReport {
            files,
            total_lines_found: total_found,
            total_lines_hit: total_hit,
            overall_line_coverage_pct: overall_pct,
        })
    }

    /// Computes the aggregate line coverage percentage for the specified implementation files.
    ///
    /// Matches file paths fuzzily by checking if the report file path ends with the given path
    /// or vice versa (to handle absolute vs relative paths).
    pub fn compute_coverage_for_files(&self, target_files: &[impl AsRef<Path>]) -> Option<f64> {
        let mut matched_found = 0;
        let mut matched_hit = 0;
        let mut matched_any = false;

        for target in target_files {
            let t_path = target.as_ref();
            let t_str = t_path.to_string_lossy();

            for (rep_path, cov) in &self.files {
                let rep_str = rep_path.to_string_lossy();
                if rep_str.ends_with(t_str.as_ref()) || t_str.ends_with(rep_str.as_ref()) {
                    matched_found += cov.lines_found;
                    matched_hit += cov.lines_hit;
                    matched_any = true;
                }
            }
        }

        if !matched_any || matched_found == 0 {
            None
        } else {
            Some((matched_hit as f64 / matched_found as f64) * 100.0)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_lcov() {
        let lcov = r#"
SF:crates/pa-core/src/auth.rs
DA:10,1
DA:11,1
DA:12,0
LF:3
LH:2
end_of_record
SF:crates/pa-core/src/token.rs
DA:1,1
DA:2,1
LF:2
LH:2
end_of_record
"#;

        let report = CoverageReport::parse(lcov).unwrap();
        assert_eq!(report.files.len(), 2);
        assert_eq!(report.total_lines_found, 5);
        assert_eq!(report.total_lines_hit, 4);
        assert!((report.overall_line_coverage_pct - 80.0).abs() < 0.01);

        let auth_cov = report
            .compute_coverage_for_files(&["crates/pa-core/src/auth.rs"])
            .unwrap();
        assert!((auth_cov - 66.67).abs() < 0.1);

        let combined = report
            .compute_coverage_for_files(&[
                "crates/pa-core/src/auth.rs",
                "crates/pa-core/src/token.rs",
            ])
            .unwrap();
        assert!((combined - 80.0).abs() < 0.01);
    }

    #[test]
    fn test_parse_llvm_cov_json() {
        let json = r#"{
            "version": "2.0.1",
            "data": [{
                "files": [
                    {
                        "filename": "/repo/crates/pa-core/src/auth.rs",
                        "summary": {
                            "lines": {
                                "count": 10,
                                "covered": 9,
                                "percent": 90.0
                            }
                        }
                    }
                ]
            }]
        }"#;

        let report = CoverageReport::parse(json).unwrap();
        assert_eq!(report.files.len(), 1);
        assert_eq!(report.total_lines_found, 10);
        assert_eq!(report.total_lines_hit, 9);
        assert!((report.overall_line_coverage_pct - 90.0).abs() < 0.01);

        let cov = report
            .compute_coverage_for_files(&["crates/pa-core/src/auth.rs"])
            .unwrap();
        assert!((cov - 90.0).abs() < 0.01);
    }
}
