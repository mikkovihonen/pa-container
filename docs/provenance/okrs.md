# Layer 0: Business Strategy (OKRs-as-Code)

PA-Container 2.0 introduces **OKRs-as-Code**, enabling engineering teams to version-control strategic objectives, quantifiable key results, and FinOps spending limits directly in Git alongside source code.

---

## 1. Motivation: Strategy-Driven Autonomous Engineering

Autonomous coding agents can rapidly generate code, but without clear boundaries they may optimize for local outputs rather than strategic business goals. By representing OKRs as declarative TOML manifests in Git:

- **Strategic Alignment:** Every requirement, feature, and task is explicitly linked to an active Key Result and Objective.
- **FinOps Guardrails:** Each Key Result can define a strict dollar spending limit (`budget_usd`).
- **Closed-Loop Feedback:** As agents execute tasks and consume LLM tokens, spending is tracked against the relevant Key Result, automatically triggering governance controls when budgets are exhausted.

---

## 2. OKR Manifest Specification

OKR manifests are stored in `docs/okrs/*.toml`. Each file declares an Objective and one or more Key Results:

```toml
[objective]
id = "OBJ-2026-Q4-SEC"
name = "Zero-Trust Agent Security & Egress Assurance"
description = "Eliminate unverified egress traffic and achieve 100% credential containment."
owner = "security-team"
period = "2026-Q4"

[[objective.key_results]]
id = "KR-SEC-01"
name = "Hardware isolation for all agent tasks"
metric = "uncontained_agent_tasks"
baseline = 12.0
target = 0.0
current = 0.0
budget_usd = 250.0
requirements = ["AUTH-01", "AUTH-02", "SEC-ISOLATE"]

[[objective.key_results]]
id = "KR-SEC-02"
name = "Zero plain-text secret exfiltration"
metric = "unredacted_egress_secrets"
baseline = 5.0
target = 0.0
current = 0.0
budget_usd = 150.0
requirements = ["AUTH-REVOKE", "PROXY-SCRUB"]
```

### Schema Reference

#### `[objective]`
- **`id`**: Unique string identifier (e.g. `OBJ-2026-Q4-SEC`).
- **`name`**: Short descriptive title.
- **`description`**: Detailed business or technical rationale.
- **`owner`**: Team or individual responsible for delivery.
- **`period`**: Execution timeframe (e.g. `2026-Q4`).

#### `[[objective.key_results]]`
- **`id`**: Unique string identifier (e.g. `KR-SEC-01`).
- **`name`**: Descriptive label for the key result.
- **`metric`**: Name of the measured operational or quality indicator.
- **`baseline`**: Numeric starting value.
- **`target`**: Target numeric threshold for completion.
- **`current`**: Current measured value (updated manually or synced from telemetry).
- **`budget_usd`**: *(Optional)* FinOps ceiling in USD. When reached, task dispatch routes to local inference or halts.
- **`requirements`**: List of technical requirement IDs (`REQ-*` or short IDs like `AUTH-01`) mapped to this Key Result.

---

## 3. Hierarchy Resolution & Traceability

`pa-core` automatically builds an in-memory bi-directional graph connecting strategy to code:

$$\text{Objective } (\text{OBJ-xxx}) \longleftrightarrow \text{Key Result } (\text{KR-xxx}) \longleftrightarrow \text{Requirement } (\text{REQ-xxx})$$

When an agent works on a feature specifying requirement `AUTH-01`:
1. `pa` resolves `AUTH-01` to `KR-SEC-01` and `OBJ-2026-Q4-SEC`.
2. The root execution span `pa.task.run` is tagged with `pa.objective_id` and `pa.kr_ids`.
3. Proxy LLM costs are metered into the local analytical store under `KR-SEC-01`.
4. The final Gate 2 merge commit is stamped with `X-PA-Requirements`, `X-PA-KRs`, and `X-PA-Objectives`.

---

## 4. CLI Inspection (`pa okr`)

### Inspecting OKR Status

View active objectives, key results, current metric values, and associated requirements:

```bash
# Display formatted terminal table of all OKRs
pa okr status

# Output as structured TOML
pa okr status --format toml

# Output as JSON for automated pipelines
pa okr status --format json
```

Example terminal output:
```text
Loaded 1 objectives from docs/okrs

Objective: OBJ-2026-Q4-SEC - Zero-Trust Agent Security & Egress Assurance
Period: 2026-Q4 | Owner: security-team
  KR-SEC-01: Hardware isolation for all agent tasks (budget: $250.00)
    Metric: uncontained_agent_tasks | Current: 0.00 / Target: 0.00
    Linked Requirements: AUTH-01, AUTH-02, SEC-ISOLATE
  KR-SEC-02: Zero plain-text secret exfiltration (budget: $150.00)
    Metric: unredacted_egress_secrets | Current: 0.00 / Target: 0.00
    Linked Requirements: AUTH-REVOKE, PROXY-SCRUB
```
