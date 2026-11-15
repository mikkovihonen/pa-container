use anyhow::{bail, Context, Result};
use serde::{Deserialize, Serialize};
use std::fs;
use std::path::{Path, PathBuf};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum FeatureStatus {
    Draft,
    Approved,
    RedPhase,
    GreenPhase,
    Verified,
    Merged,
}

impl std::fmt::Display for FeatureStatus {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Draft => write!(f, "draft"),
            Self::Approved => write!(f, "approved"),
            Self::RedPhase => write!(f, "red-phase"),
            Self::GreenPhase => write!(f, "green-phase"),
            Self::Verified => write!(f, "verified"),
            Self::Merged => write!(f, "merged"),
        }
    }
}

impl std::str::FromStr for FeatureStatus {
    type Err = anyhow::Error;

    fn from_str(s: &str) -> Result<Self> {
        match s.to_lowercase().trim() {
            "draft" => Ok(Self::Draft),
            "approved" => Ok(Self::Approved),
            "red-phase" | "red_phase" | "red" => Ok(Self::RedPhase),
            "green-phase" | "green_phase" | "green" => Ok(Self::GreenPhase),
            "verified" => Ok(Self::Verified),
            "merged" => Ok(Self::Merged),
            other => bail!("Unknown feature status: '{}'", other),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum TestKind {
    Unit,
    Integration,
    MultimodalVisual,
    IosSimulator,
}

impl std::fmt::Display for TestKind {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Unit => write!(f, "unit"),
            Self::Integration => write!(f, "integration"),
            Self::MultimodalVisual => write!(f, "multimodal-visual"),
            Self::IosSimulator => write!(f, "ios-simulator"),
        }
    }
}

impl std::str::FromStr for TestKind {
    type Err = anyhow::Error;

    fn from_str(s: &str) -> Result<Self> {
        match s.to_lowercase().trim() {
            "unit" => Ok(Self::Unit),
            "integration" => Ok(Self::Integration),
            "multimodal-visual" | "visual" | "multimodal" => Ok(Self::MultimodalVisual),
            "ios-simulator" | "ios" => Ok(Self::IosSimulator),
            other => bail!("Unknown test kind: '{}'", other),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct TaskSlice {
    pub id: usize,
    pub title: String,
    pub spec_ref: String,
    pub test_ref: String,
    pub completed: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct TestScenario {
    pub id: String,
    pub kind: TestKind,
    pub description: String,
    pub expected_outcome: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct FeatureSummary {
    pub slug: String,
    pub title: String,
    pub status: FeatureStatus,
    pub target_branch: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct Feature {
    pub slug: String,
    pub title: String,
    pub status: FeatureStatus,
    pub target_branch: String,
    pub intent: String,
    pub user_stories: Vec<String>,
    pub non_goals: Vec<String>,
    pub acceptance_criteria: Vec<String>,
    pub tasks: Vec<TaskSlice>,
    pub test_scenarios: Vec<TestScenario>,
}

impl Feature {
    pub fn new(slug: impl Into<String>, title: impl Into<String>) -> Self {
        Self {
            slug: slug.into(),
            title: title.into(),
            status: FeatureStatus::Draft,
            target_branch: "main".to_string(),
            intent: String::new(),
            user_stories: Vec::new(),
            non_goals: Vec::new(),
            acceptance_criteria: Vec::new(),
            tasks: Vec::new(),
            test_scenarios: Vec::new(),
        }
    }

    pub fn feature_dir(repo_root: &Path, slug: &str) -> PathBuf {
        repo_root.join(".pa").join("features").join(slug)
    }

    pub fn evidence_dir(repo_root: &Path, slug: &str) -> PathBuf {
        Self::feature_dir(repo_root, slug).join("evidence")
    }

    pub fn render_spec_markdown(&self) -> String {
        let mut out = String::new();
        out.push_str(&format!("# Feature: {}\n", self.title));
        out.push_str(&format!("**Slug:** `{}`\n", self.slug));
        out.push_str(&format!("**Status:** {}\n", self.status));
        out.push_str(&format!("**Target Branch:** `{}`\n\n", self.target_branch));

        out.push_str("## 1. Intent & Problem Statement\n");
        if self.intent.trim().is_empty() {
            out.push_str("*(No intent specified)*\n\n");
        } else {
            out.push_str(&format!("{}\n\n", self.intent.trim()));
        }

        out.push_str("## 2. User Stories\n");
        if self.user_stories.is_empty() {
            out.push_str("- As a developer, I want this feature to function reliably.\n\n");
        } else {
            for story in &self.user_stories {
                out.push_str(&format!("- {}\n", story));
            }
            out.push('\n');
        }

        out.push_str("## 3. Behavioral Constraints & Non-Goals\n");
        if self.non_goals.is_empty() {
            out.push_str("- MUST NOT modify unrelated modules.\n\n");
        } else {
            for ng in &self.non_goals {
                out.push_str(&format!("- {}\n", ng));
            }
            out.push('\n');
        }

        out.push_str("## 4. Acceptance Criteria\n");
        if self.acceptance_criteria.is_empty() {
            out.push_str("- [ ] Feature implemented and verified against unit tests.\n");
        } else {
            for ac in &self.acceptance_criteria {
                out.push_str(&format!("- [ ] {}\n", ac));
            }
        }

        out
    }

    pub fn render_tasks_markdown(&self) -> String {
        let mut out = String::new();
        out.push_str(&format!("# Tasks: {}\n\n", self.title));

        if self.tasks.is_empty() {
            out.push_str("- [ ] Task 1: Initial Implementation Slice\n");
            out.push_str("    - Spec ref: Section 1\n");
            out.push_str("    - Test: unit\n");
        } else {
            for task in &self.tasks {
                let mark = if task.completed { "x" } else { " " };
                out.push_str(&format!("- [{}] Task {}: {}\n", mark, task.id, task.title));
                out.push_str(&format!("    - Spec ref: {}\n", task.spec_ref));
                out.push_str(&format!("    - Test: {}\n", task.test_ref));
            }
        }

        out
    }

    pub fn render_test_plan_markdown(&self) -> String {
        let mut out = String::new();
        out.push_str(&format!("# Test Plan: {}\n\n", self.title));

        if self.test_scenarios.is_empty() {
            out.push_str("### Scenario 1: Basic Smoke Test (`unit`)\n");
            out.push_str("- **Description:** Verify primary happy path logic.\n");
            out.push_str("- **Expected Outcome:** Passes without error.\n\n");
        } else {
            for (idx, scenario) in self.test_scenarios.iter().enumerate() {
                out.push_str(&format!(
                    "### Scenario {}: {} (`{}`)\n",
                    idx + 1,
                    scenario.id,
                    scenario.kind
                ));
                out.push_str(&format!("- **Description:** {}\n", scenario.description));
                out.push_str(&format!(
                    "- **Expected Outcome:** {}\n\n",
                    scenario.expected_outcome
                ));
            }
        }

        out
    }

    pub fn save(&self, repo_root: &Path) -> Result<()> {
        let dir = Self::feature_dir(repo_root, &self.slug);
        fs::create_dir_all(&dir)
            .with_context(|| format!("Failed to create feature directory: {}", dir.display()))?;

        let evidence_dir = dir.join("evidence");
        fs::create_dir_all(&evidence_dir).with_context(|| {
            format!(
                "Failed to create evidence directory: {}",
                evidence_dir.display()
            )
        })?;

        fs::write(dir.join("spec.md"), self.render_spec_markdown())?;
        fs::write(dir.join("tasks.md"), self.render_tasks_markdown())?;
        fs::write(dir.join("test_plan.md"), self.render_test_plan_markdown())?;

        Ok(())
    }

    pub fn load(repo_root: &Path, slug: &str) -> Result<Self> {
        let dir = Self::feature_dir(repo_root, slug);
        if !dir.is_dir() {
            bail!("Feature '{}' not found at {}", slug, dir.display());
        }

        let spec_file = dir.join("spec.md");
        let spec_content = fs::read_to_string(&spec_file)
            .with_context(|| format!("Missing spec.md at {}", spec_file.display()))?;

        let mut feature = Self::parse_spec_markdown(&spec_content, slug)?;

        let tasks_file = dir.join("tasks.md");
        if tasks_file.is_file() {
            if let Ok(content) = fs::read_to_string(&tasks_file) {
                feature.tasks = Self::parse_tasks_markdown(&content);
            }
        }

        let test_plan_file = dir.join("test_plan.md");
        if test_plan_file.is_file() {
            if let Ok(content) = fs::read_to_string(&test_plan_file) {
                feature.test_scenarios = Self::parse_test_plan_markdown(&content);
            }
        }

        Ok(feature)
    }

    pub fn parse_spec_markdown(content: &str, slug_hint: &str) -> Result<Self> {
        let mut title = slug_hint.to_string();
        let mut slug = slug_hint.to_string();
        let mut status = FeatureStatus::Draft;
        let mut target_branch = "main".to_string();
        let mut intent = String::new();
        let mut user_stories = Vec::new();
        let mut non_goals = Vec::new();
        let mut acceptance_criteria = Vec::new();

        let mut current_section = "";

        for line in content.lines() {
            let trimmed = line.trim();
            if trimmed.starts_with("# Feature:") {
                title = trimmed.trim_start_matches("# Feature:").trim().to_string();
                continue;
            }
            if trimmed.starts_with("**Slug:**") {
                if let Some(s) = trimmed
                    .trim_start_matches("**Slug:**")
                    .trim()
                    .strip_prefix('`')
                    .and_then(|s| s.strip_suffix('`'))
                {
                    slug = s.to_string();
                }
                continue;
            }
            if trimmed.starts_with("**Status:**") {
                let st_str = trimmed.trim_start_matches("**Status:**").trim();
                if let Ok(st) = st_str.parse::<FeatureStatus>() {
                    status = st;
                }
                continue;
            }
            if trimmed.starts_with("**Target Branch:**") {
                if let Some(tb) = trimmed
                    .trim_start_matches("**Target Branch:**")
                    .trim()
                    .strip_prefix('`')
                    .and_then(|s| s.strip_suffix('`'))
                {
                    target_branch = tb.to_string();
                }
                continue;
            }

            if trimmed.starts_with("## 1. Intent") {
                current_section = "intent";
                continue;
            } else if trimmed.starts_with("## 2. User Stories") {
                current_section = "stories";
                continue;
            } else if trimmed.starts_with("## 3. Behavioral Constraints") {
                current_section = "non_goals";
                continue;
            } else if trimmed.starts_with("## 4. Acceptance Criteria") {
                current_section = "acceptance";
                continue;
            } else if trimmed.starts_with("## ") {
                current_section = "";
                continue;
            }

            match current_section {
                "intent" => {
                    if !trimmed.is_empty() && !trimmed.starts_with("*(") {
                        if !intent.is_empty() {
                            intent.push(' ');
                        }
                        intent.push_str(trimmed);
                    }
                }
                "stories" => {
                    if let Some(story) = trimmed.strip_prefix("- ") {
                        user_stories.push(story.to_string());
                    }
                }
                "non_goals" => {
                    if let Some(ng) = trimmed.strip_prefix("- ") {
                        non_goals.push(ng.to_string());
                    }
                }
                "acceptance" => {
                    if let Some(ac) = trimmed
                        .strip_prefix("- [ ] ")
                        .or_else(|| trimmed.strip_prefix("- [x] "))
                    {
                        acceptance_criteria.push(ac.to_string());
                    }
                }
                _ => {}
            }
        }

        Ok(Self {
            slug,
            title,
            status,
            target_branch,
            intent,
            user_stories,
            non_goals,
            acceptance_criteria,
            tasks: Vec::new(),
            test_scenarios: Vec::new(),
        })
    }

    pub fn parse_tasks_markdown(content: &str) -> Vec<TaskSlice> {
        let mut tasks = Vec::new();
        let mut current_task: Option<TaskSlice> = None;

        for line in content.lines() {
            let trimmed = line.trim();
            if trimmed.starts_with("- [ ] Task ") || trimmed.starts_with("- [x] Task ") {
                if let Some(t) = current_task.take() {
                    tasks.push(t);
                }
                let completed = trimmed.starts_with("- [x]");
                let rest = trimmed[11..].trim();
                let parts: Vec<&str> = rest.splitn(2, ':').collect();
                let id = parts[0].parse::<usize>().unwrap_or(tasks.len() + 1);
                let title = parts.get(1).map(|s| s.trim()).unwrap_or("").to_string();

                current_task = Some(TaskSlice {
                    id,
                    title,
                    spec_ref: String::new(),
                    test_ref: String::new(),
                    completed,
                });
            } else if let Some(ref mut task) = current_task {
                if trimmed.starts_with("- Spec ref:") {
                    task.spec_ref = trimmed.trim_start_matches("- Spec ref:").trim().to_string();
                } else if trimmed.starts_with("- Test:") {
                    task.test_ref = trimmed.trim_start_matches("- Test:").trim().to_string();
                }
            }
        }

        if let Some(t) = current_task {
            tasks.push(t);
        }

        tasks
    }

    pub fn parse_test_plan_markdown(content: &str) -> Vec<TestScenario> {
        let mut scenarios = Vec::new();
        let mut current_scenario: Option<TestScenario> = None;

        for line in content.lines() {
            let trimmed = line.trim();
            if trimmed.starts_with("### Scenario ") {
                if let Some(s) = current_scenario.take() {
                    scenarios.push(s);
                }

                let rest = trimmed.trim_start_matches("### Scenario ").trim();
                let colon_split: Vec<&str> = rest.splitn(2, ':').collect();
                let name_part = colon_split.get(1).map(|s| s.trim()).unwrap_or(rest);

                let (id_str, kind) = if let Some(start_paren) = name_part.rfind("(`") {
                    if let Some(end_paren) = name_part.rfind("`)") {
                        let k_str = &name_part[start_paren + 2..end_paren];
                        let id = name_part[..start_paren].trim().to_string();
                        (id, k_str.parse::<TestKind>().unwrap_or(TestKind::Unit))
                    } else {
                        (name_part.to_string(), TestKind::Unit)
                    }
                } else {
                    (name_part.to_string(), TestKind::Unit)
                };

                current_scenario = Some(TestScenario {
                    id: id_str,
                    kind,
                    description: String::new(),
                    expected_outcome: String::new(),
                });
            } else if let Some(ref mut sc) = current_scenario {
                if trimmed.starts_with("- **Description:**") {
                    sc.description = trimmed
                        .trim_start_matches("- **Description:**")
                        .trim()
                        .to_string();
                } else if trimmed.starts_with("- **Expected Outcome:**") {
                    sc.expected_outcome = trimmed
                        .trim_start_matches("- **Expected Outcome:**")
                        .trim()
                        .to_string();
                }
            }
        }

        if let Some(s) = current_scenario {
            scenarios.push(s);
        }

        scenarios
    }

    pub fn list_features(repo_root: &Path) -> Result<Vec<FeatureSummary>> {
        let features_dir = repo_root.join(".pa").join("features");
        if !features_dir.is_dir() {
            return Ok(Vec::new());
        }

        let mut results = Vec::new();
        for entry in fs::read_dir(&features_dir)? {
            let entry = entry?;
            let path = entry.path();
            if path.is_dir() {
                let slug = entry.file_name().to_string_lossy().to_string();
                if let Ok(feat) = Self::load(repo_root, &slug) {
                    results.push(FeatureSummary {
                        slug: feat.slug,
                        title: feat.title,
                        status: feat.status,
                        target_branch: feat.target_branch,
                    });
                }
            }
        }

        results.sort_by(|a, b| a.slug.cmp(&b.slug));
        Ok(results)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn test_feature_roundtrip_save_and_load() {
        let td = tempdir().unwrap();
        let repo_root = td.path();

        let mut feature = Feature::new("token-refresh", "OAuth Token Auto-Refresh");
        feature.status = FeatureStatus::Approved;
        feature.intent =
            "Automatically refresh expired OAuth2 tokens before egress proxy requests.".to_string();
        feature.user_stories.push(
            "As a client agent, I want valid tokens without manual intervention.".to_string(),
        );
        feature
            .non_goals
            .push("MUST NOT persist plain tokens on disk.".to_string());
        feature
            .acceptance_criteria
            .push("Refresh triggers 60s before expiry.".to_string());
        feature
            .acceptance_criteria
            .push("Invalid refresh triggers 401.".to_string());

        feature.tasks.push(TaskSlice {
            id: 1,
            title: "Data model for TokenCache".to_string(),
            spec_ref: "Section 4".to_string(),
            test_ref: "tests/token_test.rs::test_cache".to_string(),
            completed: true,
        });
        feature.tasks.push(TaskSlice {
            id: 2,
            title: "Proxy middleware hook".to_string(),
            spec_ref: "Section 5".to_string(),
            test_ref: "tests/proxy_test.rs::test_hook".to_string(),
            completed: false,
        });

        feature.test_scenarios.push(TestScenario {
            id: "Token Expiry Trigger".to_string(),
            kind: TestKind::Unit,
            description: "Mock token expiry timestamp and call get_token()".to_string(),
            expected_outcome: "Returns fresh token via refresh endpoint".to_string(),
        });
        feature.test_scenarios.push(TestScenario {
            id: "UI Notification Visual Check".to_string(),
            kind: TestKind::MultimodalVisual,
            description: "Check desktop tray notification during refresh".to_string(),
            expected_outcome: "Visual tray pop-up captured in screenshot".to_string(),
        });

        feature.save(repo_root).unwrap();

        let loaded = Feature::load(repo_root, "token-refresh").unwrap();
        assert_eq!(loaded.slug, "token-refresh");
        assert_eq!(loaded.title, "OAuth Token Auto-Refresh");
        assert_eq!(loaded.status, FeatureStatus::Approved);
        assert_eq!(loaded.tasks.len(), 2);
        assert!(loaded.tasks[0].completed);
        assert!(!loaded.tasks[1].completed);
        assert_eq!(loaded.test_scenarios.len(), 2);
        assert_eq!(loaded.test_scenarios[0].kind, TestKind::Unit);
        assert_eq!(loaded.test_scenarios[1].kind, TestKind::MultimodalVisual);

        let list = Feature::list_features(repo_root).unwrap();
        assert_eq!(list.len(), 1);
        assert_eq!(list[0].slug, "token-refresh");
        assert_eq!(list[0].status, FeatureStatus::Approved);
    }
}
