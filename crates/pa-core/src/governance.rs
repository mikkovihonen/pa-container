use anyhow::Result;
use serde::{Deserialize, Serialize};
use serde_json::json;

use crate::schema::{EscalationConfig, GovernanceConfig};
use crate::storage::FactoryAnalyticsStore;

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
pub enum SignalTier {
    #[serde(rename = "tier1_local_vcs")]
    Tier1LocalVcs,
    #[serde(rename = "tier2_prod")]
    Tier2Prod,
}

impl std::fmt::Display for SignalTier {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            SignalTier::Tier1LocalVcs => write!(f, "tier1_local_vcs"),
            SignalTier::Tier2Prod => write!(f, "tier2_prod"),
        }
    }
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
pub enum OptimizationTriggerKind {
    #[serde(rename = "failure_class")]
    FailureClass,
    #[serde(rename = "cfr_spike")]
    CfrSpike,
    #[serde(rename = "low_fpy")]
    LowFpy,
    #[serde(rename = "low_eval_score")]
    LowEvalScore,
    #[serde(rename = "kr_budget_overrun")]
    KrBudgetOverrun,
}

impl std::fmt::Display for OptimizationTriggerKind {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            OptimizationTriggerKind::FailureClass => write!(f, "failure_class"),
            OptimizationTriggerKind::CfrSpike => write!(f, "cfr_spike"),
            OptimizationTriggerKind::LowFpy => write!(f, "low_fpy"),
            OptimizationTriggerKind::LowEvalScore => write!(f, "low_eval_score"),
            OptimizationTriggerKind::KrBudgetOverrun => write!(f, "kr_budget_overrun"),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct OptimizationTrigger {
    pub tier: SignalTier,
    pub trigger_kind: OptimizationTriggerKind,
    pub fingerprint: String,
    pub description: String,
    pub details: serde_json::Value,
    pub sample_task_ids: Vec<String>,
}

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

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub enum EscalationDecision {
    RetrySameTier {
        tier: String,
        attempt: u32,
        failure_context: String,
    },
    Escalate {
        next_tier: String,
        require_verifier: bool,
        reason: String,
    },
    Halt {
        reason: String,
        exhausted_budget: bool,
    },
}

pub struct GovernanceEngine;

impl GovernanceEngine {
    pub fn evaluate_dispatch(
        store: &dyn FactoryAnalyticsStore,
        config: &GovernanceConfig,
        active_wip_count: usize,
        kr_id: Option<&str>,
        role: Option<&str>,
    ) -> Result<GovernanceDecision> {
        // 1. Check WIP limit based on wip_mode ("combined", "vcs_only", "local_only")
        let open_prs = store.get_open_pr_count().unwrap_or(0);
        let effective_wip = match config.wip_mode.to_lowercase().as_str() {
            "vcs_only" => open_prs,
            "local_only" => active_wip_count,
            _ => active_wip_count.max(open_prs), // "combined" (default)
        };

        if effective_wip >= config.max_wip_prs {
            return Ok(GovernanceDecision {
                allowed: false,
                reason: format!(
                    "WIP limit reached: {} active feature(s) / open PR(s) in flight (max allowed: {}, mode: '{}'). Complete or merge existing features first.",
                    effective_wip, config.max_wip_prs, config.wip_mode
                ),
                model_override: None,
                active_wip_count: effective_wip,
                current_kr_spend_usd: 0.0,
                slo_health_pct: 100.0,
                defense_mode_active: false,
            });
        }

        // 2. Check SLO Defense Mode (recent 20 tasks and rolling DORA CFR/FPY)
        let (_total, _success, success_rate) = store.get_recent_success_rate(20)?;
        let slo_target_pct = config.slo_defense_error_budget_min * 100.0;
        let mut defense_mode_active = success_rate < slo_target_pct;

        let rolling_cfr = store.get_rolling_cfr(14).unwrap_or(0.0);
        if rolling_cfr > 0.20 {
            // Over 20% change failure rate triggers defense mode
            defense_mode_active = true;
        }

        let req_role = role.unwrap_or("feature");
        let role_allowed = config
            .defense_mode_allowed_roles
            .iter()
            .any(|r| r.eq_ignore_ascii_case(req_role));

        // Hard-block disallowed roles when defense mode is active and on_slo_breach == "block"
        if defense_mode_active
            && config.on_slo_breach.eq_ignore_ascii_case("block")
            && !role_allowed
        {
            return Ok(GovernanceDecision {
                allowed: false,
                reason: format!(
                    "SLO Defense Mode active: error budget breached (recent success rate {:.1}% < {:.1}% target, CFR: {:.1}%). Role '{}' is blocked (on_slo_breach = 'block'). Allowed roles: {:?}. Remediate open production issues with bugfix or triage tasks first.",
                    success_rate, slo_target_pct, rolling_cfr * 100.0, req_role, config.defense_mode_allowed_roles
                ),
                model_override: None,
                active_wip_count: effective_wip,
                current_kr_spend_usd: 0.0,
                slo_health_pct: success_rate,
                defense_mode_active: true,
            });
        }

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
                    "SLO Defense Mode active: recent success rate {:.1}% is below target {:.1}% (or CFR {:.1}% > 20%). Permitted role '{}' operating under observation.",
                    success_rate, slo_target_pct, rolling_cfr * 100.0, req_role
                ),
            )
        } else {
            (None, "Governance compliance checks passed.".to_string())
        };

        Ok(GovernanceDecision {
            allowed: true,
            reason,
            model_override,
            active_wip_count: effective_wip,
            current_kr_spend_usd: kr_spend,
            slo_health_pct: success_rate,
            defense_mode_active,
        })
    }

    #[allow(clippy::too_many_arguments)]
    pub fn evaluate_escalation(
        store: &dyn FactoryAnalyticsStore,
        escalation_cfg: &EscalationConfig,
        gov_cfg: &GovernanceConfig,
        _task_id: &str,
        current_tier: &str,
        attempt_on_tier: u32,
        failure_kind: &str,
        failure_context: &str,
        kr_id: Option<&str>,
    ) -> Result<EscalationDecision> {
        if !escalation_cfg.enabled {
            return Ok(EscalationDecision::Halt {
                reason: "Upward escalation is disabled in configuration.".to_string(),
                exhausted_budget: false,
            });
        }

        let is_configured_failure = escalation_cfg
            .escalate_on
            .iter()
            .any(|k| k.eq_ignore_ascii_case(failure_kind));
        if !is_configured_failure {
            return Ok(EscalationDecision::Halt {
                reason: format!(
                    "Failure kind '{}' is not configured for automatic escalation (configured: {:?}).",
                    failure_kind, escalation_cfg.escalate_on
                ),
                exhausted_budget: false,
            });
        }

        // 1. Can we retry on the same tier?
        if attempt_on_tier < escalation_cfg.max_retries_per_tier {
            return Ok(EscalationDecision::RetrySameTier {
                tier: current_tier.to_string(),
                attempt: attempt_on_tier + 1,
                failure_context: failure_context.to_string(),
            });
        }

        // 2. We need to escalate to the next tier in chain
        let norm_current = current_tier.to_lowercase();
        let current_idx = escalation_cfg.chain.iter().position(|t| {
            let norm_t = t.to_lowercase();
            norm_current == norm_t
                || norm_current.contains(&norm_t)
                || norm_t.contains(&norm_current)
        });

        let next_idx = match current_idx {
            Some(idx) => idx + 1,
            None => 1,
        };

        if next_idx >= escalation_cfg.chain.len() {
            return Ok(EscalationDecision::Halt {
                reason: format!(
                    "Exhausted escalation chain ({:?}) on tier '{}' after {} attempt(s).",
                    escalation_cfg.chain, current_tier, attempt_on_tier
                ),
                exhausted_budget: false,
            });
        }

        let next_tier_spec = &escalation_cfg.chain[next_idx];

        // 3. Check FinOps guardrail if next tier is paid/frontier
        let is_paid_tier = !next_tier_spec.to_lowercase().starts_with("local");
        if escalation_cfg.respect_kr_budget && is_paid_tier {
            let kr_spend = if let Some(kr) = kr_id {
                store.get_kr_spend(kr).unwrap_or(0.0)
            } else {
                0.0
            };

            if kr_spend >= gov_cfg.budget_usd_per_kr {
                return Ok(EscalationDecision::Halt {
                    reason: format!(
                        "Key Result budget exhausted (${:.2} spent >= ${:.2} budget); upward escalation to '{}' blocked. Use --force to override.",
                        kr_spend, gov_cfg.budget_usd_per_kr, next_tier_spec
                    ),
                    exhausted_budget: true,
                });
            }
        }

        let require_verifier = next_tier_spec.contains("+verifier");
        let clean_tier = next_tier_spec.replace("+verifier", "");

        Ok(EscalationDecision::Escalate {
            next_tier: clean_tier,
            require_verifier,
            reason: format!(
                "Escalating from '{}' (after {} attempt(s)) to '{}' due to {}.",
                current_tier, attempt_on_tier, next_tier_spec, failure_kind
            ),
        })
    }

    pub fn resolve_initial_tier(
        store: &dyn FactoryAnalyticsStore,
        escalation_cfg: &EscalationConfig,
        gov_cfg: &GovernanceConfig,
        role: &str,
        requested_tier: &str,
        kr_id: Option<&str>,
    ) -> Result<(String, Option<String>)> {
        if !escalation_cfg.enabled {
            return Ok((requested_tier.to_string(), None));
        }

        if requested_tier.to_lowercase().contains("local") {
            let (sample_size, fpy, cfr) = store.get_model_tier_stats(Some(role), requested_tier)?;
            let rolling_eval = store
                .get_rolling_eval_score(14, None, Some(requested_tier))
                .unwrap_or(1.0);
            let eval_breached = sample_size >= escalation_cfg.min_sample_size
                && rolling_eval < escalation_cfg.min_first_pass_yield;

            if sample_size >= escalation_cfg.min_sample_size
                && (fpy < escalation_cfg.min_first_pass_yield
                    || cfr > escalation_cfg.max_change_failure_rate
                    || eval_breached)
            {
                let kr_spend = if let Some(kr) = kr_id {
                    store.get_kr_spend(kr).unwrap_or(0.0)
                } else {
                    0.0
                };

                let next_tier = escalation_cfg
                    .chain
                    .iter()
                    .find(|t| !t.to_lowercase().starts_with("local"))
                    .cloned()
                    .unwrap_or_else(|| "frontier".to_string());

                if escalation_cfg.respect_kr_budget && kr_spend >= gov_cfg.budget_usd_per_kr {
                    return Ok((
                        requested_tier.to_string(),
                        Some(format!(
                            "Proactive promotion to '{}' suppressed: KR budget exhausted (${:.2} >= ${:.2}).",
                            next_tier, kr_spend, gov_cfg.budget_usd_per_kr
                        )),
                    ));
                }

                let reason = if eval_breached && fpy >= escalation_cfg.min_first_pass_yield {
                    format!(
                        "Proactive tier promotion: rolling eval score {:.1}% (< {:.1}%) over {} tasks for role '{}' on '{}'. Promoted to '{}'.",
                        rolling_eval * 100.0,
                        escalation_cfg.min_first_pass_yield * 100.0,
                        sample_size,
                        role,
                        requested_tier,
                        next_tier
                    )
                } else {
                    format!(
                        "Proactive tier promotion: rolling FPY {:.1}% (< {:.1}%) / CFR {:.1}% (> {:.1}%) over {} tasks for role '{}' on '{}'. Promoted to '{}'.",
                        fpy * 100.0,
                        escalation_cfg.min_first_pass_yield * 100.0,
                        cfr * 100.0,
                        escalation_cfg.max_change_failure_rate * 100.0,
                        sample_size,
                        role,
                        requested_tier,
                        next_tier
                    )
                };
                return Ok((next_tier, Some(reason)));
            }
        }

        Ok((requested_tier.to_string(), None))
    }

    pub fn evaluate_self_optimization(
        store: &dyn FactoryAnalyticsStore,
        gov_config: &GovernanceConfig,
        _factory_config: Option<&crate::schema::FactoryConfig>,
    ) -> Result<Vec<OptimizationTrigger>> {
        let opt_cfg = &gov_config.self_optimization;
        if !opt_cfg.enabled {
            return Ok(Vec::new());
        }

        let window_days = opt_cfg.window_days;
        let cooldown_hours = opt_cfg.cooldown_hours;
        let mut triggers = Vec::new();

        // 1. Recurring failure classes (Tier 1 local & Tier 2 prod)
        let recurring =
            store.detect_recurring_failure_classes(window_days, opt_cfg.min_failure_class_count)?;
        for rec in recurring {
            let tier = match rec.signal_tier.as_str() {
                "tier1_local_vcs" => SignalTier::Tier1LocalVcs,
                _ => SignalTier::Tier2Prod,
            };
            let fp = format!("failure_class:{}", rec.failure_class);
            if !store
                .has_recent_optimization_event(&fp, cooldown_hours)
                .unwrap_or(false)
            {
                triggers.push(OptimizationTrigger {
                    tier,
                    trigger_kind: OptimizationTriggerKind::FailureClass,
                    fingerprint: fp,
                    description: format!(
                        "Recurring failure class '{}' detected ({} occurrences in {} days, tier: {})",
                        rec.failure_class, rec.count, window_days, rec.signal_tier
                    ),
                    details: json!({
                        "failure_class": rec.failure_class,
                        "count": rec.count,
                        "signal_tier": rec.signal_tier,
                        "sample_ids": rec.sample_ids,
                    }),
                    sample_task_ids: rec.sample_ids,
                });
            }
        }

        // 2. DORA metrics: CFR spike and low FPY
        if let Ok(dora) = store.get_dora_flow_report(window_days, None) {
            if dora.total_merged_prs > 0 {
                if dora.change_failure_rate > opt_cfg.cfr_spike_threshold {
                    let fp = "cfr_spike:dora".to_string();
                    if !store
                        .has_recent_optimization_event(&fp, cooldown_hours)
                        .unwrap_or(false)
                    {
                        triggers.push(OptimizationTrigger {
                            tier: SignalTier::Tier1LocalVcs,
                            trigger_kind: OptimizationTriggerKind::CfrSpike,
                            fingerprint: fp,
                            description: format!(
                                "Change Failure Rate spike: {:.1}% exceeds threshold of {:.1}% ({} merged PRs)",
                                dora.change_failure_rate * 100.0,
                                opt_cfg.cfr_spike_threshold * 100.0,
                                dora.total_merged_prs
                            ),
                            details: json!({
                                "change_failure_rate": dora.change_failure_rate,
                                "threshold": opt_cfg.cfr_spike_threshold,
                                "total_merged_prs": dora.total_merged_prs,
                            }),
                            sample_task_ids: Vec::new(),
                        });
                    }
                }

                if dora.first_pass_yield < opt_cfg.min_rolling_fpy {
                    let fp = "low_fpy:dora".to_string();
                    if !store
                        .has_recent_optimization_event(&fp, cooldown_hours)
                        .unwrap_or(false)
                    {
                        triggers.push(OptimizationTrigger {
                            tier: SignalTier::Tier1LocalVcs,
                            trigger_kind: OptimizationTriggerKind::LowFpy,
                            fingerprint: fp,
                            description: format!(
                                "Low First Pass Yield: {:.1}% is below threshold of {:.1}% ({} merged PRs)",
                                dora.first_pass_yield * 100.0,
                                opt_cfg.min_rolling_fpy * 100.0,
                                dora.total_merged_prs
                            ),
                            details: json!({
                                "first_pass_yield": dora.first_pass_yield,
                                "threshold": opt_cfg.min_rolling_fpy,
                                "total_merged_prs": dora.total_merged_prs,
                            }),
                            sample_task_ids: Vec::new(),
                        });
                    }
                }
            }
        }

        // 3. Eval summary: aggregate or per-rubric low score
        if let Ok(evals) = store.get_eval_summary(window_days) {
            if evals.total_evals > 0 && evals.mean_score < opt_cfg.min_eval_score {
                let fp = "low_eval_score:aggregate".to_string();
                if !store
                    .has_recent_optimization_event(&fp, cooldown_hours)
                    .unwrap_or(false)
                {
                    triggers.push(OptimizationTrigger {
                        tier: SignalTier::Tier1LocalVcs,
                        trigger_kind: OptimizationTriggerKind::LowEvalScore,
                        fingerprint: fp,
                        description: format!(
                            "Low overall evaluation score: {:.2} is below threshold {:.2} across {} evaluations",
                            evals.mean_score, opt_cfg.min_eval_score, evals.total_evals
                        ),
                        details: json!({
                            "mean_score": evals.mean_score,
                            "threshold": opt_cfg.min_eval_score,
                            "total_evals": evals.total_evals,
                            "pass_rate": evals.pass_rate,
                        }),
                        sample_task_ids: Vec::new(),
                    });
                }
            }

            for (rubric_id, stat) in &evals.by_rubric {
                if stat.count >= 2 && stat.mean_score < opt_cfg.min_eval_score {
                    let fp = format!("low_eval_score:{}", rubric_id);
                    if !store
                        .has_recent_optimization_event(&fp, cooldown_hours)
                        .unwrap_or(false)
                    {
                        triggers.push(OptimizationTrigger {
                            tier: SignalTier::Tier1LocalVcs,
                            trigger_kind: OptimizationTriggerKind::LowEvalScore,
                            fingerprint: fp,
                            description: format!(
                                "Eval rubric '{}' mean score {:.2} is below threshold {:.2} ({} evaluations)",
                                rubric_id, stat.mean_score, opt_cfg.min_eval_score, stat.count
                            ),
                            details: json!({
                                "rubric_id": rubric_id,
                                "mean_score": stat.mean_score,
                                "threshold": opt_cfg.min_eval_score,
                                "count": stat.count,
                            }),
                            sample_task_ids: Vec::new(),
                        });
                    }
                }
            }
        }

        // 4. KR Budget overruns
        if let Ok(snapshots) = store.list_kr_snapshots(None, 100) {
            let mut seen_krs = std::collections::HashSet::new();
            for s in snapshots {
                if seen_krs.insert(s.kr_id.clone()) {
                    let spend = store.get_kr_spend(&s.kr_id).unwrap_or(0.0);
                    let budget = gov_config.budget_usd_per_kr;
                    if budget > 0.0 && spend >= budget * opt_cfg.kr_budget_warn_pct {
                        let fp = format!("kr_budget_overrun:{}", s.kr_id);
                        if !store
                            .has_recent_optimization_event(&fp, cooldown_hours)
                            .unwrap_or(false)
                        {
                            triggers.push(OptimizationTrigger {
                                tier: SignalTier::Tier1LocalVcs,
                                trigger_kind: OptimizationTriggerKind::KrBudgetOverrun,
                                fingerprint: fp,
                                description: format!(
                                    "KR '{}' spend ${:.2} reached {:.1}% of budget ${:.2}",
                                    s.kr_id,
                                    spend,
                                    (spend / budget) * 100.0,
                                    budget
                                ),
                                details: json!({
                                    "kr_id": s.kr_id,
                                    "spend_usd": spend,
                                    "budget_usd": budget,
                                    "spend_pct": (spend / budget) * 100.0,
                                }),
                                sample_task_ids: Vec::new(),
                            });
                        }
                    }
                }
            }
        }

        Ok(triggers)
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
            wip_mode: "combined".to_string(),
            ..Default::default()
        };

        let decision = GovernanceEngine::evaluate_dispatch(&store, &cfg, 3, None, None).unwrap();
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
            wip_mode: "combined".to_string(),
            ..Default::default()
        };

        // Record a task with $12 cost linked to KR-AUTH-01
        let mut ctx = TaskContext::new("feat-expensive-01");
        ctx.kr_ids = vec!["KR-AUTH-01".to_string()];
        ctx.cost_usd = Some(12.50);
        store.record_task(&ctx, "verified").unwrap();

        let decision =
            GovernanceEngine::evaluate_dispatch(&store, &cfg, 1, Some("KR-AUTH-01"), None).unwrap();
        assert!(decision.allowed);
        assert_eq!(
            decision.model_override.as_deref(),
            Some("llama-server:local")
        );
        assert!(decision.reason.contains("budget guardrail active"));
    }

    #[test]
    fn test_governance_slo_defense_mode_blocks_feature() {
        let td = tempdir().unwrap();
        let store = SqliteAnalyticsStore::open_or_create(&td.path().join("factory.db")).unwrap();
        let cfg = GovernanceConfig {
            max_wip_prs: 5,
            slo_defense_error_budget_min: 0.95, // 95% minimum
            budget_usd_per_kr: 100.0,
            wip_mode: "combined".to_string(),
            on_slo_breach: "block".to_string(),
            defense_mode_allowed_roles: vec!["bugfix".to_string(), "triage".to_string()],
            ..Default::default()
        };

        // Record 1 failed and 1 verified task (50% pass rate)
        let ctx1 = TaskContext::new("task-fail-01");
        store.record_task(&ctx1, "failed").unwrap();
        let ctx2 = TaskContext::new("task-pass-01");
        store.record_task(&ctx2, "verified").unwrap();

        // 1. Role "feature" should be blocked
        let decision_feature =
            GovernanceEngine::evaluate_dispatch(&store, &cfg, 1, None, Some("feature")).unwrap();
        assert!(!decision_feature.allowed);
        assert!(decision_feature.defense_mode_active);
        assert_eq!(decision_feature.slo_health_pct, 50.0);
        assert!(decision_feature.reason.contains("SLO Defense Mode active"));
        assert!(decision_feature
            .reason
            .contains("Role 'feature' is blocked"));

        // 2. Role "bugfix" should be allowed
        let decision_bugfix =
            GovernanceEngine::evaluate_dispatch(&store, &cfg, 1, None, Some("bugfix")).unwrap();
        assert!(decision_bugfix.allowed);
        assert!(decision_bugfix.defense_mode_active);
        assert!(decision_bugfix
            .reason
            .contains("Permitted role 'bugfix' operating under observation"));
    }

    #[test]
    fn test_governance_slo_defense_mode_warn_mode() {
        let td = tempdir().unwrap();
        let store = SqliteAnalyticsStore::open_or_create(&td.path().join("factory.db")).unwrap();
        let cfg = GovernanceConfig {
            max_wip_prs: 5,
            slo_defense_error_budget_min: 0.95,
            budget_usd_per_kr: 100.0,
            wip_mode: "combined".to_string(),
            on_slo_breach: "warn".to_string(),
            ..Default::default()
        };

        let ctx1 = TaskContext::new("task-fail-01");
        store.record_task(&ctx1, "failed").unwrap();
        let ctx2 = TaskContext::new("task-pass-01");
        store.record_task(&ctx2, "verified").unwrap();

        let decision =
            GovernanceEngine::evaluate_dispatch(&store, &cfg, 1, None, Some("feature")).unwrap();
        assert!(decision.allowed);
        assert!(decision.defense_mode_active);
        assert_eq!(decision.slo_health_pct, 50.0);
        assert!(decision.reason.contains("SLO Defense Mode active"));
    }

    #[test]
    fn test_governance_vcs_wip_modes() {
        let td = tempdir().unwrap();
        let store = SqliteAnalyticsStore::open_or_create(&td.path().join("factory.db")).unwrap();

        // Insert 3 open PRs into vcs_outcomes
        for i in 1..=3 {
            let record = crate::storage::VcsOutcomeRecord {
                pr_id: format!("pr-{}", i),
                task_id: Some(format!("task-{}", i)),
                repo: "org/repo".to_string(),
                pr_number: i,
                state: "open".to_string(),
                opened_at: "1000".to_string(),
                first_review_at: None,
                merged_at: None,
                human_review_rounds: 0,
                human_commits_added: 0,
                ci_runs_count: 1,
                ci_failed_first_run: false,
                reverted: false,
                lead_time_sec: None,
                synced_at: "1100".to_string(),
            };
            store.upsert_vcs_outcome(&record).unwrap();
        }

        // 1. wip_mode = "combined" with max_wip_prs = 3, local_wip = 1
        // effective_wip = max(1, 3) = 3 >= 3 -> should block
        let cfg_combined = GovernanceConfig {
            max_wip_prs: 3,
            slo_defense_error_budget_min: 0.95,
            budget_usd_per_kr: 100.0,
            wip_mode: "combined".to_string(),
            ..Default::default()
        };
        let d_comb =
            GovernanceEngine::evaluate_dispatch(&store, &cfg_combined, 1, None, None).unwrap();
        assert!(!d_comb.allowed);
        assert!(d_comb.reason.contains("WIP limit reached"));

        // 2. wip_mode = "local_only" with max_wip_prs = 3, local_wip = 1
        // effective_wip = 1 < 3 -> should allow
        let cfg_local = GovernanceConfig {
            max_wip_prs: 3,
            slo_defense_error_budget_min: 0.95,
            budget_usd_per_kr: 100.0,
            wip_mode: "local_only".to_string(),
            ..Default::default()
        };
        let d_local =
            GovernanceEngine::evaluate_dispatch(&store, &cfg_local, 1, None, None).unwrap();
        assert!(d_local.allowed);

        // 3. wip_mode = "vcs_only" with max_wip_prs = 3, local_wip = 0
        // effective_wip = 3 >= 3 -> should block
        let cfg_vcs = GovernanceConfig {
            max_wip_prs: 3,
            slo_defense_error_budget_min: 0.95,
            budget_usd_per_kr: 100.0,
            wip_mode: "vcs_only".to_string(),
            ..Default::default()
        };
        let d_vcs = GovernanceEngine::evaluate_dispatch(&store, &cfg_vcs, 0, None, None).unwrap();
        assert!(!d_vcs.allowed);
    }

    #[test]
    fn test_escalation_lifecycle_and_budget_guardrail() {
        let td = tempdir().unwrap();
        let store = SqliteAnalyticsStore::open_or_create(&td.path().join("factory.db")).unwrap();
        let gov_cfg = GovernanceConfig {
            budget_usd_per_kr: 50.0,
            ..Default::default()
        };
        let esc_cfg = EscalationConfig {
            enabled: true,
            chain: vec![
                "local".to_string(),
                "frontier".to_string(),
                "frontier+verifier".to_string(),
            ],
            max_retries_per_tier: 2,
            escalate_on: vec!["test_failure".to_string(), "gate_failure".to_string()],
            respect_kr_budget: true,
            ..Default::default()
        };

        // 1. Attempt 1 on local fails test -> should retry same tier
        let d1 = GovernanceEngine::evaluate_escalation(
            &store,
            &esc_cfg,
            &gov_cfg,
            "t1",
            "local",
            1,
            "test_failure",
            "assertion failed: 1 == 2",
            Some("KR-1"),
        )
        .unwrap();
        assert_eq!(
            d1,
            EscalationDecision::RetrySameTier {
                tier: "local".to_string(),
                attempt: 2,
                failure_context: "assertion failed: 1 == 2".to_string(),
            }
        );

        // 2. Attempt 2 on local fails test -> should escalate to frontier
        let d2 = GovernanceEngine::evaluate_escalation(
            &store,
            &esc_cfg,
            &gov_cfg,
            "t1",
            "local",
            2,
            "test_failure",
            "syntax error",
            Some("KR-1"),
        )
        .unwrap();
        match d2 {
            EscalationDecision::Escalate {
                next_tier,
                require_verifier,
                ..
            } => {
                assert_eq!(next_tier, "frontier");
                assert!(!require_verifier);
            }
            other => panic!("Expected Escalate, got {:?}", other),
        }

        // 3. Attempt 2 on frontier fails gate -> should escalate to frontier+verifier
        let d3 = GovernanceEngine::evaluate_escalation(
            &store,
            &esc_cfg,
            &gov_cfg,
            "t1",
            "frontier",
            2,
            "gate_failure",
            "traceability < 95%",
            Some("KR-1"),
        )
        .unwrap();
        match d3 {
            EscalationDecision::Escalate {
                next_tier,
                require_verifier,
                ..
            } => {
                assert_eq!(next_tier, "frontier");
                assert!(require_verifier);
            }
            other => panic!("Expected Escalate with verifier, got {:?}", other),
        }

        // 4. Budget exhausted: record $55 spend on KR-1 -> escalation to frontier is halted
        let mut spend_ctx = TaskContext::new("prior-task");
        spend_ctx.kr_ids = vec!["KR-1".to_string()];
        spend_ctx.cost_usd = Some(55.0);
        store.record_task(&spend_ctx, "completed").unwrap();

        let d_budget = GovernanceEngine::evaluate_escalation(
            &store,
            &esc_cfg,
            &gov_cfg,
            "t1",
            "local",
            2,
            "test_failure",
            "fatal error",
            Some("KR-1"),
        )
        .unwrap();
        match d_budget {
            EscalationDecision::Halt {
                exhausted_budget,
                reason,
            } => {
                assert!(exhausted_budget);
                assert!(reason.contains("Key Result budget exhausted"));
            }
            other => panic!("Expected Halt due to budget, got {:?}", other),
        }
    }

    #[test]
    fn test_proactive_tier_promotion() {
        let td = tempdir().unwrap();
        let store = SqliteAnalyticsStore::open_or_create(&td.path().join("factory.db")).unwrap();
        let gov_cfg = GovernanceConfig {
            budget_usd_per_kr: 100.0,
            ..Default::default()
        };
        let esc_cfg = EscalationConfig {
            enabled: true,
            chain: vec!["local".to_string(), "frontier".to_string()],
            min_first_pass_yield: 0.80,
            max_change_failure_rate: 0.20,
            min_sample_size: 5,
            respect_kr_budget: true,
            ..Default::default()
        };

        // Initially no samples -> stays on local
        let (tier1, reason1) = GovernanceEngine::resolve_initial_tier(
            &store,
            &esc_cfg,
            &gov_cfg,
            "feature",
            "local",
            Some("KR-1"),
        )
        .unwrap();
        assert_eq!(tier1, "local");
        assert!(reason1.is_none());

        // Record 5 tasks: 2 verified, 3 failed -> FPY = 40% < 80%
        for i in 0..5 {
            let mut ctx = TaskContext::new(format!("feat-sample-{}", i));
            ctx.agent_role = Some("feature".to_string());
            ctx.model_profile = Some("llama-server:local".to_string());
            let status = if i < 2 { "verified" } else { "failed" };
            store.record_task(&ctx, status).unwrap();
        }

        let (tier2, reason2) = GovernanceEngine::resolve_initial_tier(
            &store,
            &esc_cfg,
            &gov_cfg,
            "feature",
            "local",
            Some("KR-1"),
        )
        .unwrap();
        assert_eq!(tier2, "frontier");
        assert!(reason2.unwrap().contains("Proactive tier promotion"));
    }

    #[test]
    fn test_self_optimization_tier1_only() {
        let td = tempdir().unwrap();
        let store = SqliteAnalyticsStore::open_or_create(&td.path().join("factory.db")).unwrap();
        let gov_cfg = GovernanceConfig {
            self_optimization: crate::schema::SelfOptimizationConfig {
                enabled: true,
                min_rolling_fpy: 0.70,
                cfr_spike_threshold: 0.15,
                cooldown_hours: 24,
                ..Default::default()
            },
            ..Default::default()
        };

        // Seed 4 merged PRs: 2 clean first-pass, 2 reverted -> FPY = 50% (< 70%), CFR = 50% (> 15%)
        for i in 0..4 {
            let pr = crate::storage::VcsOutcomeRecord {
                pr_id: format!("pr-{}", i),
                task_id: Some(format!("task-{}", i)),
                repo: "org/repo".to_string(),
                pr_number: (i + 1) as u64,
                state: "merged".to_string(),
                opened_at: "2026-11-20T10:00:00Z".to_string(),
                first_review_at: None,
                merged_at: Some("2026-11-20T12:00:00Z".to_string()),
                human_review_rounds: 0,
                human_commits_added: 0,
                ci_runs_count: 1,
                ci_failed_first_run: i >= 2,
                reverted: i >= 2,
                lead_time_sec: Some(7200.0),
                synced_at: "2026-11-20T12:05:00Z".to_string(),
            };
            store.upsert_vcs_outcome(&pr).unwrap();
        }

        let triggers =
            GovernanceEngine::evaluate_self_optimization(&store, &gov_cfg, None).unwrap();
        assert!(!triggers.is_empty());
        let kinds: Vec<OptimizationTriggerKind> = triggers.iter().map(|t| t.trigger_kind).collect();
        assert!(kinds.contains(&OptimizationTriggerKind::CfrSpike));
        assert!(kinds.contains(&OptimizationTriggerKind::LowFpy));
        assert!(triggers.iter().all(|t| t.tier == SignalTier::Tier1LocalVcs));
    }

    #[test]
    fn test_self_optimization_tier2_prod_signals() {
        let td = tempdir().unwrap();
        let store = SqliteAnalyticsStore::open_or_create(&td.path().join("factory.db")).unwrap();
        let gov_cfg = GovernanceConfig {
            self_optimization: crate::schema::SelfOptimizationConfig {
                enabled: true,
                window_days: 30,
                min_failure_class_count: 2,
                cooldown_hours: 24,
                ..Default::default()
            },
            ..Default::default()
        };

        // Insert 2 prod signals with failure_class = "db_lock" within window
        for i in 1..=2 {
            let sig = crate::storage::ProdSignalRecord {
                signal_id: format!("sig-{}", i),
                task_id: Some(format!("task-{}", i)),
                deploy_sha: "abcd123".to_string(),
                environment: "prod".to_string(),
                observed_at: "2026-11-24T10:00:00Z".to_string(),
                error_rate_delta: 0.05,
                p95_latency_delta_ms: 120.0,
                slo_budget_burn_pct: 0.10,
                incident_triggered: true,
                mttr_sec: Some(300.0),
                failure_class: Some("db_lock".to_string()),
            };
            store.insert_prod_signal(&sig).unwrap();
        }

        // Insert 1 older signal (> 30 days old)
        let old_sig = crate::storage::ProdSignalRecord {
            signal_id: "sig-old".to_string(),
            task_id: None,
            deploy_sha: "abcd123".to_string(),
            environment: "prod".to_string(),
            observed_at: "2026-09-01T10:00:00Z".to_string(),
            error_rate_delta: 0.05,
            p95_latency_delta_ms: 120.0,
            slo_budget_burn_pct: 0.10,
            incident_triggered: true,
            mttr_sec: Some(300.0),
            failure_class: Some("out_of_memory".to_string()),
        };
        store.insert_prod_signal(&old_sig).unwrap();

        let triggers =
            GovernanceEngine::evaluate_self_optimization(&store, &gov_cfg, None).unwrap();
        let db_lock_trigger = triggers
            .iter()
            .find(|t| t.fingerprint == "failure_class:db_lock");
        assert!(db_lock_trigger.is_some());
        let t = db_lock_trigger.unwrap();
        assert_eq!(t.tier, SignalTier::Tier2Prod);
        assert_eq!(t.trigger_kind, OptimizationTriggerKind::FailureClass);

        // "out_of_memory" only occurred once in 30d window, should not fire
        assert!(triggers
            .iter()
            .all(|t| t.fingerprint != "failure_class:out_of_memory"));

        // Record optimization event for db_lock (cooling down)
        let evt = crate::storage::OptimizationEventRecord {
            event_id: "evt-1".to_string(),
            signal_tier: "tier2_prod".to_string(),
            trigger_kind: "failure_class".to_string(),
            fingerprint: "failure_class:db_lock".to_string(),
            details_json: "{}".to_string(),
            action_taken: "hardened".to_string(),
            linked_task_id: None,
            created_at: "2026-11-24T12:00:00Z".to_string(),
        };
        store.record_optimization_event(&evt).unwrap();

        // Second evaluation should deduplicate db_lock due to 24h cooldown
        let triggers2 =
            GovernanceEngine::evaluate_self_optimization(&store, &gov_cfg, None).unwrap();
        assert!(triggers2
            .iter()
            .all(|t| t.fingerprint != "failure_class:db_lock"));
    }
}
