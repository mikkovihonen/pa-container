use anyhow::Result;
use serde::{Deserialize, Serialize};

use crate::schema::GovernanceConfig;
use crate::storage::FactoryAnalyticsStore;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct GovernanceDecision {
    pub allowed: bool,
    pub reason: String,
    pub model_override: Option<String>,
    pub active_wip_count: usize,
    pub current_kr_spend_usd: f64,
    pub slo_health_pct: f64,
    pub defense_mode_active: bool,
}

pub struct GovernanceEngine;

impl GovernanceEngine {
    pub fn evaluate_dispatch(
        store: &dyn FactoryAnalyticsStore,
        config: &GovernanceConfig,
        active_wip_count: usize,
        kr_id: Option<&str>,
    ) -> Result<GovernanceDecision> {
        // 1. Check WIP limit
        if active_wip_count >= config.max_wip_prs {
            return Ok(GovernanceDecision {
                allowed: false,
                reason: format!(
                    "WIP limit reached: {} active feature(s) in flight (max allowed: {}). Complete or merge existing features first.",
                    active_wip_count, config.max_wip_prs
                ),
                model_override: None,
                active_wip_count,
                current_kr_spend_usd: 0.0,
                slo_health_pct: 100.0,
                defense_mode_active: false,
            });
        }

        // 2. Check SLO Defense Mode (recent 20 tasks)
        let (_total, _success, success_rate) = store.get_recent_success_rate(20)?;
        let slo_target_pct = config.slo_defense_error_budget_min * 100.0;
        let defense_mode_active = success_rate < slo_target_pct;

        // 3. Check Key Result budget guardrail
        let kr_spend = if let Some(kr) = kr_id {
            store.get_kr_spend(kr)?
        } else {
            0.0
        };

        let (model_override, reason) = if kr_spend >= config.budget_usd_per_kr {
            (
                Some("llama-server:local".to_string()),
                format!(
                    "Key Result budget guardrail active (${:.2} spent >= ${:.2} budget). Downgrading to local llama-server.",
                    kr_spend, config.budget_usd_per_kr
                ),
            )
        } else if defense_mode_active {
            (
                None,
                format!(
                    "SLO Defense Mode active: recent success rate {:.1}% is below target {:.1}%.",
                    success_rate, slo_target_pct
                ),
            )
        } else {
            (None, "Governance compliance checks passed.".to_string())
        };

        Ok(GovernanceDecision {
            allowed: true,
            reason,
            model_override,
            active_wip_count,
            current_kr_spend_usd: kr_spend,
            slo_health_pct: success_rate,
            defense_mode_active,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::storage::SqliteAnalyticsStore;
    use crate::telemetry::TaskContext;
    use tempfile::tempdir;

    #[test]
    fn test_governance_wip_limit_blocks_dispatch() {
        let td = tempdir().unwrap();
        let store = SqliteAnalyticsStore::open_or_create(&td.path().join("factory.db")).unwrap();
        let cfg = GovernanceConfig {
            max_wip_prs: 3,
            slo_defense_error_budget_min: 0.95,
            budget_usd_per_kr: 50.0,
        };

        let decision = GovernanceEngine::evaluate_dispatch(&store, &cfg, 3, None).unwrap();
        assert!(!decision.allowed);
        assert!(decision.reason.contains("WIP limit reached"));
    }

    #[test]
    fn test_governance_kr_budget_downgrades_model() {
        let td = tempdir().unwrap();
        let store = SqliteAnalyticsStore::open_or_create(&td.path().join("factory.db")).unwrap();
        let cfg = GovernanceConfig {
            max_wip_prs: 5,
            slo_defense_error_budget_min: 0.95,
            budget_usd_per_kr: 10.0,
        };

        // Record a task with $12 cost linked to KR-AUTH-01
        let mut ctx = TaskContext::new("feat-expensive-01");
        ctx.kr_ids = vec!["KR-AUTH-01".to_string()];
        ctx.cost_usd = Some(12.50);
        store.record_task(&ctx, "verified").unwrap();

        let decision =
            GovernanceEngine::evaluate_dispatch(&store, &cfg, 1, Some("KR-AUTH-01")).unwrap();
        assert!(decision.allowed);
        assert_eq!(
            decision.model_override.as_deref(),
            Some("llama-server:local")
        );
        assert!(decision.reason.contains("budget guardrail active"));
    }

    #[test]
    fn test_governance_slo_defense_mode() {
        let td = tempdir().unwrap();
        let store = SqliteAnalyticsStore::open_or_create(&td.path().join("factory.db")).unwrap();
        let cfg = GovernanceConfig {
            max_wip_prs: 5,
            slo_defense_error_budget_min: 0.95, // 95% minimum
            budget_usd_per_kr: 100.0,
        };

        // Record 1 failed and 1 verified task (50% pass rate)
        let ctx1 = TaskContext::new("task-fail-01");
        store.record_task(&ctx1, "failed").unwrap();
        let ctx2 = TaskContext::new("task-pass-01");
        store.record_task(&ctx2, "verified").unwrap();

        let decision = GovernanceEngine::evaluate_dispatch(&store, &cfg, 1, None).unwrap();
        assert!(decision.allowed);
        assert!(decision.defense_mode_active);
        assert_eq!(decision.slo_health_pct, 50.0);
        assert!(decision.reason.contains("SLO Defense Mode active"));
    }
}
