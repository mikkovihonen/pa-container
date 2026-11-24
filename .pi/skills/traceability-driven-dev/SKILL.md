---
name: traceability-driven-dev
description: Guidelines and conventions for OpenFastTrace and StrictDoc requirement, implementation, test execution, and code coverage traceability
---

# Traceability-Driven Development (OpenFastTrace & StrictDoc)

This skill guides autonomous agents (`spec_architect`, `traceability_auditor`, `feature`, `verifier`) in declaring, maintaining, and verifying bi-directional traceability across OKRs, functional requirements, source code implementations, test executions, and line coverage.

---

## 1. Traceability Engines

PA-Container 2.0 supports two unified traceability engines selectable via `factory.toml` (`[traceability] engine = "openfasttrace" | "strictdoc"`):
- **OpenFastTrace (`openfasttrace`)**: Lightweight inline tags in Markdown specs and source comments (`req~`, `impl~`, `utest~`, `vtest~`).
- **StrictDoc (`strictdoc`)**: Structured `.sdoc` specification documents and source-level `@relation(...)` annotations.

---

## 2. OpenFastTrace Tag Syntax

OpenFastTrace uses lightweight tag conventions embedded directly within Markdown specifications and source code comments.

### 2.1 Specification Definitions (`docs/specs/*.md`)
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

### 2.2 Implementation Tags (Source Code)
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

### 2.3 Test Linkage Tags (Unit & Verification Tests)
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

## 3. StrictDoc Syntax

StrictDoc structures technical requirements in `.sdoc` documents cross-referenced with source-code annotations.

### 3.1 StrictDoc Document Definitions (`docs/specs/*.sdoc`)
```sdoc
[DOCUMENT]
TITLE: Authentication & Authorization Specification

[REQUIREMENT]
UID: REQ-AUTH-001
TITLE: OAuth Token Rotation
STATEMENT: The system shall rotate access tokens upon expiration using a valid refresh token.
RELATIONS:
- TYPE: Parent
  VALUE: KR-AUTH-01

[REQUIREMENT]
UID: REQ-AUTH-002
TITLE: Immediate Revocation
STATEMENT: The system shall immediately invalidate all active sessions upon password reset.
RELATIONS:
- TYPE: Parent
  VALUE: KR-AUTH-01
```

### 3.2 StrictDoc Source Annotations
Attach `@relation` annotations to functions or files:
- **Implementation:**
    - `// @relation(REQ-AUTH-001, scope=function)`
    - `# @relation(REQ-AUTH-001, scope=file)`
- **Test Verification:**
    - In test directories (`tests/`, `test/`) or test files (`*_test.rs`, `test_*.py`):
        - `// @relation(REQ-AUTH-001, scope=function)`
    - Or explicit relation types:
        - `// @relation(REQ-AUTH-001, type=Verifies)`

---

## 4. Test Execution Verification & Code Coverage

Static tags in code are necessary but insufficient for verification when `require_test_execution = true`. A requirement is only marked verified when its linked test actually executed and passed in the current run.

### 4.1 Generating JUnit XML Test Reports
Configure tests to emit standard JUnit XML into `.pa/reports/junit.xml` (or paths listed in `junit_report_paths`):
- **Rust (`cargo-nextest`):**
  ```bash
  cargo nextest run --profile default --junit-path .pa/reports/junit.xml
  ```
- **Python (`pytest`):**
  ```bash
  pytest --junitxml=.pa/reports/junit.xml
  ```
- **TypeScript / JavaScript (`vitest` / `jest`):**
  ```bash
  vitest run --reporter=junit --outputFile=.pa/reports/junit.xml
  ```

### 4.2 Generating Code Coverage Reports
Configure coverage tools to export LCOV (`lcov.info`) or JSON (`llvm-cov` / `gcov`) to `.pa/reports/lcov.info`:
- **Rust (`cargo-llvm-cov`):**
  ```bash
  cargo llvm-cov --lcov --output-path .pa/reports/lcov.info
  ```
- **Python (`pytest-cov`):**
  ```bash
  pytest --cov=src --cov-report=lcov:.pa/reports/lcov.info
  ```

---

## 5. Configuration (`factory.toml`)

```toml
[traceability]
engine = "openfasttrace"                # "openfasttrace" | "strictdoc" | "custom_cmd" | "none"
spec_dir = "docs/specs"                 # Directory containing specs (.md or .sdoc)
min_coverage_pct = 95.0                 # Minimum requirement linkage percentage (0.0 - 100.0)
enforce_test_linkage = true             # Require test tags for all requirements
junit_report_paths = [".pa/reports/junit.xml"]  # List of JUnit XML test report paths
coverage_report_path = ".pa/reports/lcov.info" # Optional LCOV or gcov/llvm-cov JSON report
require_test_execution = true           # Hard-fail gate if tests did not pass in JUnit XML
min_line_coverage_pct = 80.0            # Optional minimum line coverage threshold
on_missing_tool = "skip"                # "skip" | "block" for external CLI binaries (e.g. strictdoc)
```

---

## 6. CLI Inspection & Verification

Check traceability gate compliance manually:
```bash
# Basic check using factory.toml configuration
pa traceability check

# Check with StrictDoc engine and execution verification
pa traceability check --engine strictdoc --junit .pa/reports/junit.xml --require-test-execution

# Check with coverage threshold and machine-readable JSON output
pa traceability check --coverage .pa/reports/lcov.info --min-line-coverage 80.0 --json
```

---

## 7. Auto-Remediation Workflow for `traceability_auditor`

When the traceability gate reports missing links or unexecuted tests:
- Locate untagged test functions and append the corresponding tag:
    - OpenFastTrace: `// utest~<REQ-ID>~1`
    - StrictDoc: `// @relation(REQ-ID, scope=function)`
- Verify test suites are executed with JUnit XML export enabled before running the gate.
- If line coverage falls below threshold, add unit test assertions covering the missing branches in the implementing file.
- Re-run `pa traceability check` to verify compliance before stamping `X-PA-Traceability` trailers.
