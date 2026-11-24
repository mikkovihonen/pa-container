#!/usr/bin/env bash
# End-to-End Test Execution Verification (JUnit / Coverage & StrictDoc Engine)
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)
cd "$REPO_ROOT"

echo "=========================================================="
echo " PA-Container 2.0: E2E Traceability Execution Verification"
echo " Platform: $(uname -s) ($(uname -m))"
echo "=========================================================="

export PA_TEST_MODE=1
export PA_DISABLE_KEYRING=1
PA_BIN="cargo run --quiet --bin pa --"

TMP_DIR=$(mktemp -d /tmp/pa-traceability-test-XXXXXX)
TEST_CONFIG="$TMP_DIR/factory.toml"
TEST_DB="$TMP_DIR/factory.db"

cleanup() {
    rm -rf "$TMP_DIR"
}
trap cleanup EXIT

# Setup test workspace
SPECS_DIR="$TMP_DIR/docs/specs"
SRC_DIR="$TMP_DIR/crates/app/src"
TESTS_DIR="$TMP_DIR/crates/app/tests"
REPORTS_DIR="$TMP_DIR/.pa/reports"

mkdir -p "$SPECS_DIR" "$SRC_DIR" "$TESTS_DIR" "$REPORTS_DIR"

# 1. Author OpenFastTrace specification and implementation
cat <<'EOF' > "$SPECS_DIR/auth.md"
# Authentication Specification

- req~AUTH-ROTATION~1: Rotate expired refresh tokens safely.
    - Parent Key Result: `KR-AUTH-01`
- req~AUTH-REVOKE~1: Revoke tokens upon user logout.
    - Parent Key Result: `KR-AUTH-01`
EOF

cat <<'EOF' > "$SRC_DIR/auth.rs"
// impl~AUTH-ROTATION~1
pub fn rotate_token() -> bool { true }

// impl~AUTH-REVOKE~1
pub fn revoke_token() -> bool { true }
EOF

cat <<'EOF' > "$TESTS_DIR/auth_test.rs"
// utest~AUTH-ROTATION~1
#[test]
fn test_rotate_token() {
    assert!(true);
}

// utest~AUTH-REVOKE~1
#[test]
fn test_revoke_token() {
    assert!(true);
}
EOF

# Author passing JUnit XML
cat <<'EOF' > "$REPORTS_DIR/junit_pass.xml"
<?xml version="1.0" encoding="UTF-8"?>
<testsuites tests="2" failures="0" errors="0">
    <testsuite name="auth_suite" tests="2" failures="0" errors="0">
        <testcase name="test_rotate_token" classname="auth_test" file="crates/app/tests/auth_test.rs" time="0.02"/>
        <testcase name="test_revoke_token" classname="auth_test" file="crates/app/tests/auth_test.rs" time="0.01"/>
    </testsuite>
</testsuites>
EOF

# Author failing JUnit XML
cat <<'EOF' > "$REPORTS_DIR/junit_fail.xml"
<?xml version="1.0" encoding="UTF-8"?>
<testsuites tests="2" failures="1" errors="0">
    <testsuite name="auth_suite" tests="2" failures="1" errors="0">
        <testcase name="test_rotate_token" classname="auth_test" file="crates/app/tests/auth_test.rs" time="0.02"/>
        <testcase name="test_revoke_token" classname="auth_test" file="crates/app/tests/auth_test.rs" time="0.01">
            <failure message="assertion failed: token is still active">Session not terminated</failure>
        </testcase>
    </testsuite>
</testsuites>
EOF

# Author LCOV report
cat <<'EOF' > "$REPORTS_DIR/lcov.info"
SF:crates/app/src/auth.rs
DA:2,1
DA:5,1
LF:2
LH:2
end_of_record
EOF

cat <<EOF > "$TEST_CONFIG"
[storage]
provider = "sqlite"
path = "$TEST_DB"

[traceability]
engine = "openfasttrace"
spec_dir = "$SPECS_DIR"
min_coverage_pct = 95.0
enforce_test_linkage = true
junit_report_paths = ["$REPORTS_DIR/junit_pass.xml"]
coverage_report_path = "$REPORTS_DIR/lcov.info"
require_test_execution = true
min_line_coverage_pct = 80.0
on_missing_tool = "skip"

[telemetry.otlp]
provider = "none"
EOF

# Change to TMP_DIR to simulate repository workspace
pushd "$TMP_DIR" >/dev/null

echo "==> Test 1: OpenFastTrace with Passing Execution & Coverage"
REPORT_JSON=$($REPO_ROOT/target/debug/pa traceability check --config "$TEST_CONFIG" --json)
echo "$REPORT_JSON"

IS_COMPLIANT=$(echo "$REPORT_JSON" | grep -o '"is_compliant": *[a-z]*' | head -1 | cut -d: -f2 | tr -d ' ')
TOTAL_REQS=$(echo "$REPORT_JSON" | grep -o '"total_requirements": *[0-9]*' | head -1 | cut -d: -f2 | tr -d ' ')
TESTS_PASSED=$(echo "$REPORT_JSON" | grep -o '"tests_passed": *[0-9]*' | head -1 | cut -d: -f2 | tr -d ' ')

if [ "$IS_COMPLIANT" != "true" ] || [ "$TOTAL_REQS" -ne 2 ] || [ "$TESTS_PASSED" -ne 2 ]; then
    echo "[FAIL] Expected compliant report with 2 reqs and 2 passed tests"
    exit 1
fi
echo "[PASS] Test 1: OFT passing execution verified."

echo "==> Test 2: Failing Test Execution Hard-Fails Gate"
set +e
FAIL_OUT=$($REPO_ROOT/target/debug/pa traceability check --config "$TEST_CONFIG" --junit "$REPORTS_DIR/junit_fail.xml" 2>&1)
FAIL_CODE=$?
set -e

if [ $FAIL_CODE -eq 0 ]; then
    echo "[FAIL] Expected non-zero exit code when linked test failed"
    exit 1
fi
echo "[PASS] Test 2: Failing test blocked gate as expected (exit code $FAIL_CODE)."

echo "==> Test 3: Missing Required JUnit Report Hard-Fails Gate"
set +e
MISSING_OUT=$($REPO_ROOT/target/debug/pa traceability check --config "$TEST_CONFIG" --junit "$REPORTS_DIR/nonexistent.xml" --require-test-execution 2>&1)
MISSING_CODE=$?
set -e

if [ $MISSING_CODE -eq 0 ]; then
    echo "[FAIL] Expected non-zero exit code when required JUnit XML is missing"
    exit 1
fi
echo "[PASS] Test 3: Missing JUnit XML hard-failed gate as expected."

echo "==> Test 4: Line Coverage Threshold Violation Fails Gate"
set +e
COV_FAIL_OUT=$($REPO_ROOT/target/debug/pa traceability check --config "$TEST_CONFIG" --min-line-coverage 100.1 2>&1)
COV_FAIL_CODE=$?
set -e

if [ $COV_FAIL_CODE -eq 0 ]; then
    echo "[FAIL] Expected failure when line coverage falls below threshold"
    exit 1
fi
echo "[PASS] Test 4: Line coverage threshold violation blocked gate."

echo "==> Test 5: StrictDoc Engine with .sdoc Requirements & @relation Annotations"
# Create .sdoc spec
cat <<'EOF' > "$SPECS_DIR/security.sdoc"
[DOCUMENT]
TITLE: Security Requirements

[REQUIREMENT]
UID: REQ-SEC-MFA
TITLE: Multi-Factor Authentication
STATEMENT: Enforce MFA for administrative logins.
RELATIONS:
- TYPE: Parent
  VALUE: KR-SEC-01

[REQUIREMENT]
UID: REQ-SEC-AUDIT
TITLE: Audit Trail
STATEMENT: Write tamper-proof audit records.
RELATIONS:
- TYPE: Parent
  VALUE: KR-SEC-02
EOF

# Create source with @relation annotations
cat <<'EOF' > "$SRC_DIR/sec.rs"
// @relation(REQ-SEC-MFA, scope=function)
pub fn verify_mfa() -> bool { true }

// @relation(REQ-SEC-AUDIT, scope=function)
pub fn write_audit() -> bool { true }
EOF

# Create tests with @relation annotations
cat <<'EOF' > "$TESTS_DIR/sec_test.rs"
// @relation(REQ-SEC-MFA, scope=function)
#[test]
fn test_verify_mfa() {
    assert!(true);
}

// @relation(REQ-SEC-AUDIT, scope=function)
#[test]
fn test_write_audit() {
    assert!(true);
}
EOF

cat <<'EOF' > "$REPORTS_DIR/sec_junit.xml"
<testsuite name="sec_tests">
    <testcase name="test_verify_mfa" classname="sec_test" file="crates/app/tests/sec_test.rs" time="0.01"/>
    <testcase name="test_write_audit" classname="sec_test" file="crates/app/tests/sec_test.rs" time="0.01"/>
</testsuite>
EOF

cat <<'EOF' > "$REPORTS_DIR/sec_lcov.info"
SF:crates/app/src/sec.rs
DA:2,1
DA:5,1
LF:2
LH:2
end_of_record
EOF

SDOC_REPORT=$($REPO_ROOT/target/debug/pa traceability check \
    --engine strictdoc \
    --junit "$REPORTS_DIR/sec_junit.xml" \
    --coverage "$REPORTS_DIR/sec_lcov.info" \
    --require-test-execution \
    --min-line-coverage 80.0 \
    --json)

echo "$SDOC_REPORT"

SDOC_COMPLIANT=$(echo "$SDOC_REPORT" | grep -o '"is_compliant": *[a-z]*' | head -1 | cut -d: -f2 | tr -d ' ')
SDOC_ENGINE=$(echo "$SDOC_REPORT" | grep -o '"engine": *"[^"]*"' | head -1 | cut -d'"' -f4)
SDOC_PASSED=$(echo "$SDOC_REPORT" | grep -o '"tests_passed": *[0-9]*' | head -1 | cut -d: -f2 | tr -d ' ')

if [ "$SDOC_COMPLIANT" != "true" ] || [ "$SDOC_ENGINE" != "strictdoc" ] || [ "$SDOC_PASSED" -ne 2 ]; then
    echo "[FAIL] StrictDoc verification failed compliance check"
    exit 1
fi
echo "[PASS] Test 5: StrictDoc engine parsed .sdoc, correlated @relation tags, and verified test execution."

popd >/dev/null

echo "=========================================================="
echo " ALL E2E TRACEABILITY VERIFICATION TESTS PASSED SUCCESSFULLY"
echo "=========================================================="
