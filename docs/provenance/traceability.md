# Layer 1: Functional Traceability

PA-Container 2.0 embeds a native requirements traceability scanner compatible with the [OpenFastTrace](https://openfasttrace.org) and [StrictDoc](https://strictdoc.readthedocs.io) standards. It ensures that every line of generated code connects to a verified requirement and an automated test.

---

## 1. Specification Tags

Requirements and their verification evidence are declared in code and documentation using standard tilde tags:

| Tag Pattern | Semantic Meaning | Scanned Locations |
| :--- | :--- | :--- |
| `req~<id>~<ver>` | **Requirement Definition:** Declares a formal functional or non-functional requirement. | Markdown specifications (`docs/specs/`, `.pa/features/`, `docs/`) |
| `impl~<id>~<ver>` | **Implementation:** Marks source code satisfying a specific requirement. | Source code directories (`crates/`, `src/`, etc.) |
| `utest~<id>~<ver>` | **Unit Test:** Marks automated unit tests verifying the requirement. | Unit test files and functions |
| `vtest~<id>~<ver>` | **Verification Test:** Marks integration, E2E, or visual verification tests. | Integration test suites (`tests/`) |

### Example Tag Usage

#### 1. Specification Document (`docs/specs/auth.md`)
```markdown
# Authentication Requirements

req~AUTH-01~1
The system shall verify HMAC nonces on all incoming agent requests.
```

#### 2. Source Code Implementation (`crates/pa-core/src/auth.rs`)
```rust
// impl~AUTH-01~1
pub fn verify_agent_nonce(nonce: &str, signature: &[u8]) -> bool {
    // cryptographic verification...
}
```

#### 3. Automated Test (`tests/auth_test.rs`)
```rust
// utest~AUTH-01~1
#[test]
fn test_nonce_verification() {
    assert!(verify_agent_nonce(VALID_NONCE, VALID_SIG));
}
```

---

## 2. Scoping & Anti-Tamper Invariants

To prevent false positives and assertion gaming:
- **Strict Requirement Scoping:** `req~` tags are extracted exclusively from specification documents (`docs/specs/`, `.pa/features/`, and Markdown documents). Any accidental string literal or comment inside source code (e.g. in test assertions) is ignored for requirement declaration.
- **Bi-directional Verification:** Every declared requirement must have at least one valid implementation tag (`impl~`) and at least one test tag (`utest~` or `vtest~`).
- **Orphan Detection:** Code with `impl~` tags referencing non-existent requirements triggers a lint warning or error in strict mode.

---

## 3. Configuration in `factory.toml`

Traceability settings are configured under `[traceability]`:

```toml
[traceability]
enabled = true
# Engine: "openfasttrace", "strictdoc", "custom_cmd", or "none"
engine = "openfasttrace"
spec_dir = "docs/specs"
scan_dirs = ["crates", "src", "tests", "docs"]
min_coverage_pct = 80.0
strict_mode = false
```

### Options
- **`enabled`**: Master switch for the traceability gate.
- **`engine`**: Active provider adapter:
    - `"openfasttrace"` *(Default)*: Uses the native OpenFastTrace tag scanner.
    - `"strictdoc"`: Integrates with StrictDoc specification manifests.
    - `"custom_cmd"`: Invokes an external traceability verification binary.
    - `"none"`: Disables traceability gating cleanly.
- **`spec_dir`**: Primary directory where requirement definitions reside.
- **`scan_dirs`**: List of source and test directories to scan for implementation and test tags.
- **`min_coverage_pct`**: Minimum test and implementation coverage percentage required to pass the gate (defaults to `80.0`).
- **`strict_mode`**: When `true`, missing tests or implementations immediately fail the pipeline rather than emitting warnings.

---

## 4. Running the Traceability Check

Inspect traceability coverage across your workspace:

```bash
# Run traceability verification
pa traceability check

# Output structured JSON for CI/CD gates
pa traceability check --json
```

Example terminal output:
```text
Running OpenFastTrace scan...
Requirements Found: 5
Implemented: 5 / 5 (100.0%)
Tested: 5 / 5 (100.0%)
Traceability Gate: PASSED (Coverage 100.0% >= 80.0%)
```
