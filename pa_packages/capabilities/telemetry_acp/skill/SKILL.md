---
name: telemetry_acp
description: Read-only operational context from the software factory control plane, including OKR alignment, factory health, recent failure diagnostics, and SLO defense status.
---

# Factory Telemetry Context Skill

This skill provides read-only operational telemetry tools powered by the `telemetry_acp` Model Context Protocol (MCP) server. Agents use these tools to establish architectural and operational context before and during code implementation.

## Available Tools

- `telemetry.get_okr_context(kr_id: str)`
    - Reads objective definitions from `docs/okrs/*.toml` and snapshots/spends from `.pa/factory.db`.
    - Returns objective title, owner, KR baseline, target, current value, calculated progress percentage, allocated budget, and recent linked tasks.
    - Usage: Call when beginning work on a feature tied to a Key Result or when checking business alignment.
- `telemetry.get_factory_health(window_days: int = 30)`
    - Reads rolling First Pass Yield (FPY), Change Failure Rate (CFR), task success rate, and active Work-In-Progress (WIP) pull request queue depth.
    - Also inspects upstream live Prometheus metrics if configured in `factory.toml`.
    - Usage: Call during triage or diagnostics to check if the factory pipeline is healthy or saturated.
- `telemetry.query_recent_failures(limit: int = 10, role: str = None)`
    - Queries failed tasks and verification gate rejections from `.pa/factory.db`, along with live Phoenix OTLP traces if configured.
    - Usage: Call during root-cause analysis or bugfix tasks to learn from previous verification failures.
- `telemetry.get_slo_status()`
    - Evaluates the current Service Level Objective (SLO) error budget and determines whether the factory is operating normally or is locked in SLO Defense Mode.
    - Lists allowed emergency roles (e.g. `bugfix`, `triage`, `verifier`).
    - Usage: Call before scheduling high-risk refactors to verify error budget availability.

## Invocation Guidelines

- **Read-Only Invariant:** These tools never mutate database records or files.
- **Host Execution:** The server runs exclusively on the Host Control Plane outside the sandbox.
