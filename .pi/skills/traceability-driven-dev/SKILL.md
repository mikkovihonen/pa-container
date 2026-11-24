---
name: traceability-driven-dev
description: Guidelines and conventions for OpenFastTrace requirement, implementation, and test traceability
---

# Traceability-Driven Development (OpenFastTrace & StrictDoc)

This skill guides autonomous agents (`spec_architect`, `traceability_auditor`, `feature`, `verifier`) in declaring, maintaining, and verifying bi-directional traceability across OKRs, functional requirements, source code implementations, and test cases.

## 1. OpenFastTrace Tag Syntax

OpenFastTrace uses lightweight, language-agnostic tag conventions embedded directly within Markdown specifications and source code comments.

### 1.1 Specification Definitions (`docs/specs/*.md`)
Define functional requirements with a unique alphanumeric identifier:
- `req~<REQUIREMENT-ID>~<VERSION>`
- Example: `req~AUTH-TOKEN-ROTATION~1`

When linking a requirement to a Key Result:
```markdown
# Functional Specification: Token Rotation

- req~AUTH-TOKEN-ROTATION~1: Automatically rotate expired OAuth tokens.
    - Parent Key Result: `KR-AUTH-01`
    - Acceptance Criteria: Fails closed when refresh token is revoked.
```

### 1.2 Implementation Tags (Source Code)
Every source code block or function implementing a requirement MUST carry an implementation tag inside comments:

```rust
// impl~AUTH-TOKEN-ROTATION~1
pub fn rotate_oauth_token(refresh_token: &str) -> Result<TokenPair> {
    // Implementation logic...
}
```

```python
# impl~AUTH-TOKEN-ROTATION~1
def rotate_oauth_token(refresh_token: str) -> TokenPair:
    pass
```

### 1.3 Test Tags (Unit & Verification Tests)
Every test scenario verifying a requirement MUST declare its test linkage:

```rust
// utest~AUTH-TOKEN-ROTATION~1
#[test]
fn test_rotate_oauth_token_success() {
    // Test assertion...
}
```

```python
# utest~AUTH-TOKEN-ROTATION~1
def test_rotate_oauth_token_success():
    assert True
```

For end-to-end or multimodal visual verification:
```rust
// vtest~AUTH-TOKEN-ROTATION~1
#[test]
fn test_ui_shows_token_refresh_toast() {
    // Visual or simulator check...
}
```

---

## 2. Quality Gate Rules (`builtin:traceability`)

The Software Factory automatically evaluates traceability compliance before committing or approving code:
1. **Zero Unlinked Requirements:**
    - Every `req~` MUST have at least one corresponding `impl~`.
2. **Mandatory Test Linkage:**
    - When `enforce_test_linkage = true`, every `req~` MUST have at least one `utest~` or `vtest~`.
3. **Coverage Threshold:**
    - The repository coverage percentage must meet or exceed `min_coverage_pct` (default: 95.0%).

---

## 3. Auto-Remediation Workflow for `traceability_auditor`

When the traceability gate reports missing links without code logic errors:
- Locate untagged test functions and append the corresponding `// utest~<REQ-ID>~1` comment.
- Ensure all acceptance criteria in `tasks.md` reference valid `req~` identifiers.
- Re-run `pa traceability check` to verify 100% compliance before stamping `X-PA-Traceability` trailers.

---

## 4. Operational Context & OKR Telemetry via MCP (`telemetry_acp`)

Autonomous agents bound to `telemetry_acp:read` have access to read-only operational context tools:

- `telemetry.get_okr_context(kr_id: str)`:
    - Call this before authoring a functional specification to pull the objective title, target metrics, current progress %, and already linked requirements.
    - Example: `telemetry.get_okr_context(kr_id="KR-AUTH-01")`.
- `telemetry.get_slo_status()`:
    - Call this before scheduling new feature work to verify error budget health. If `defense_mode_active: true`, only emergency roles (`bugfix`, `triage`, `verifier`) may proceed.
- `telemetry.query_recent_failures(limit: int, role: str)`:
    - Call during triage or bugfixing to inspect recent gate rejections and root causes across the factory.
- `telemetry.get_factory_health()`:
    - Inspect rolling First Pass Yield (FPY), Change Failure Rate (CFR), and WIP saturation.
