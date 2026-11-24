---
name: closed-loop-governance
description: Guidelines and conventions for closed-loop governance, WIP limits, SLO Defense Mode, and Key Result budget guardrails
---

# Closed-Loop Software Factory Governance

This skill guides analytical meta-roles (`factory_diagnostician`, `okr_analyst`, `lead_orchestrator`) in inspecting operational outcomes, enforcing WIP constraints, activating SLO Defense Mode, and managing FinOps Key Result budget guardrails.

## 1. Governance Architecture

The Software Factory employs a closed-loop control system joining runtime telemetry (`factory.db`), business strategy (`docs/okrs/*.toml`), and operational metrics.

### 1.1 Governance Guardrails (`[governance]` in `factory.toml`)
1. **WIP Limits (`max_wip_prs`):**
    - Enforces maximum concurrent in-flight feature branches (`Approved`, `RedPhase`, `GreenPhase`, `Verified`).
    - Dispatches are rejected when active features meet or exceed the limit.
2. **SLO Defense Mode (`slo_defense_error_budget_min`):**
    - Evaluates the rolling success rate across the last 20 tasks.
    - If success rate falls below the error budget threshold (e.g., 99.0%), non-critical feature dispatches are gated to prioritize `bugfix` and `test_hardening` roles.
3. **Key Result Budget Throttling (`budget_usd_per_kr`):**
    - Monitors cumulative LLM proxy inference spend against Key Result targets.
    - When budget is exhausted, inference is automatically routed to standard tiers or local `llama-server`.

---

## 2. Analytical Meta-Roles

### 2.1 Factory Diagnostician (`factory_diagnostician`)
- **Mission:** Investigate broken builds, gate failures, OTLP trace anomalies, and recurring production failure classes.
- **Workflow:**
    - Query task failure logs via `pa logs` and inspect span attributes via `pa telemetry trace <TASK-ID>`.
    - Access read-only operational telemetry through `telemetry_acp` tools (`telemetry.query_recent_failures`, `telemetry.get_factory_health`, `telemetry.get_slo_status`).
    - Classify failure root causes across Tier 1 (local build/eval/revert anomalies) and Tier 2 (`prod_signals` production incidents).
    - Author new dormant `[[quality_gates]]` entries in `factory.toml` for recurring failure classes.
    - Author diagnostic runbooks under `docs/runbooks/<failure_class>.md` detailing failure conditions and mitigation commands.

### 2.2 OKR Analyst (`okr_analyst`)
- **Mission:** Evaluate technical execution progress against Key Result metric baselines and targets.
- **Workflow:**
    - Ingest operational metrics via `pa telemetry report` and `pa okr brief`.
    - Compare baseline, current, and target values in `docs/okrs/*.toml`.
    - Correlate technical DORA flow outcomes with business Key Result metrics.
    - Generate structured executive OKR briefs saved to `docs/okrs/reports/` and recorded in SQLite `optimization_events`.
    - Verify FinOps burn rates stay within allocated `budget_usd` guardrails and flag budget overruns.

---

## 3. Operational Outcome & Self-Optimization Commands

- `pa telemetry report`: Outputs summary of tasks, pass/fail rates, DORA outcomes, and KR spend.
- `pa telemetry sync`: Ingests offline logs and syncs analytical database.
- `pa telemetry harden`: Evaluates recurring anomalies across Tier 1 and Tier 2, proposing dormant gate activations.
- `pa telemetry harden --apply`: Formats and activates matching dormant quality gates directly in `factory.toml` via `toml_edit`.
- `pa telemetry record-signal`: Records operational or production signals (`failure_class`, incident flag, error/latency delta).
- `pa okr status`: Visualizes Objectives, Key Results, metric targets, and linked specifications.
- `pa okr brief`: Generates executive OKR progress, FinOps spend, and budget-risk brief.
