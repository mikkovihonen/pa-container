#!/usr/bin/env bash
# End-to-End Test for Closed-Loop Self-Optimization (factory_diagnostician, okr_analyst & pa telemetry harden)
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)
cd "$REPO_ROOT"

echo "=========================================================="
echo " PA-Container 2.0: E2E Closed-Loop Self-Optimization"
echo " Platform: $(uname -s) ($(uname -m))"
echo "=========================================================="

export PA_TEST_MODE=1
export PA_DISABLE_KEYRING=1
PA_BIN="cargo run --quiet --bin pa --"

TMP_DIR=$(mktemp -d /tmp/pa-self-opt-test-XXXXXX)
TEST_CONFIG="$TMP_DIR/factory.toml"
TEST_DB="$TMP_DIR/.pa/factory.db"
OKRS_DIR="$TMP_DIR/docs/okrs"

cleanup() {
    rm -rf "$TMP_DIR"
}
trap cleanup EXIT

mkdir -p "$TMP_DIR/.pa" "$OKRS_DIR"

# 1. Setup factory.toml with dormant quality gate and self_optimization configuration
cat <<EOF > "$TEST_CONFIG"
schema_version = "2.1"

[storage]
provider = "sqlite"
path = "$TEST_DB"

[governance]
enabled = true
max_wip_prs = 5
slo_defense_error_budget_min = 0.95
budget_usd_per_kr = 50.0

[governance.self_optimization]
enabled = true
window_days = 30
min_failure_class_count = 2
cfr_spike_threshold = 0.15
min_rolling_fpy = 0.70
cooldown_hours = 24
auto_enqueue_diagnostician = true
auto_enqueue_okr_analyst = true
in_place_apply = true

# Dormant gate for db_lock failure class
[[quality_gates]]
name = "db-concurrency-gate"
command = "cargo test -p pa-core test_db"
trigger = "failure_class:db_lock"
enabled = false
description = "Hardened automatically when db_lock recurs"
EOF

# 2. Setup sample OKR manifest
cat <<'EOF' > "$OKRS_DIR/q4_reliability.toml"
schema_version = "1.0"

[objective]
id = "OBJ-REL-01"
title = "Enterprise Reliability & Hardening"
description = "Zero regression delivery and automated defense"
owner = "lead_orchestrator"
budget_usd = 200.0

[[key_results]]
id = "KR-REL-01"
title = "Zero concurrency deadlocks"
baseline = 0.0
target = 100.0
current = 80.0
budget_usd = 50.0
linked_reqs = ["REQ-DB-01"]
EOF

echo "==> Step 1: Record operational/production signals via CLI..."
$PA_BIN telemetry record-signal --config "$TEST_CONFIG" --failure-class db_lock --incident --environment prod
$PA_BIN telemetry record-signal --config "$TEST_CONFIG" --failure-class db_lock --incident --environment prod
$PA_BIN telemetry record-signal --config "$TEST_CONFIG" --failure-class oom_spike --incident --environment staging
$PA_BIN telemetry record-signal --config "$TEST_CONFIG" --failure-class oom_spike --incident --environment staging

echo "==> Step 2: Run dry-run telemetry harden..."
DRY_RUN_JSON=$($PA_BIN telemetry harden --config "$TEST_CONFIG" --json)
echo "$DRY_RUN_JSON" | jq .

HAS_CHANGES=$(echo "$DRY_RUN_JSON" | jq -r '.has_changes')
if [ "$HAS_CHANGES" != "true" ]; then
    echo "ERROR: Expected has_changes to be true in dry run"
    exit 1
fi

ACTIVATED_COUNT=$(echo "$DRY_RUN_JSON" | jq '.activated_gates | length')
if [ "$ACTIVATED_COUNT" -ne 1 ]; then
    echo "ERROR: Expected 1 activated gate (db_lock), got $ACTIVATED_COUNT"
    exit 1
fi

ACTIVATED_NAME=$(echo "$DRY_RUN_JSON" | jq -r '.activated_gates[0].gate_name')
if [ "$ACTIVATED_NAME" != "db-concurrency-gate" ]; then
    echo "ERROR: Expected activated gate to be db-concurrency-gate, got $ACTIVATED_NAME"
    exit 1
fi

UNMATCHED_COUNT=$(echo "$DRY_RUN_JSON" | jq '.unmatched_failure_classes | length')
if [ "$UNMATCHED_COUNT" -ne 1 ]; then
    echo "ERROR: Expected 1 unmatched failure class (oom_spike), got $UNMATCHED_COUNT"
    exit 1
fi

UNMATCHED_NAME=$(echo "$DRY_RUN_JSON" | jq -r '.unmatched_failure_classes[0].failure_class')
if [ "$UNMATCHED_NAME" != "oom_spike" ]; then
    echo "ERROR: Expected unmatched failure class to be oom_spike, got $UNMATCHED_NAME"
    exit 1
fi

# Assert factory.toml quality_gates has NOT been modified during dry run
if grep -A 5 "\[\[quality_gates\]\]" "$TEST_CONFIG" | grep -q "enabled = true"; then
    echo "ERROR: factory.toml quality_gates was modified during dry-run"
    exit 1
fi

echo "==> Step 3: Run telemetry harden with --apply..."
APPLY_OUTPUT=$($PA_BIN telemetry harden --config "$TEST_CONFIG" --apply)
echo "$APPLY_OUTPUT"

# Assert factory.toml quality_gates has been hardened in-place
if ! grep -A 5 "\[\[quality_gates\]\]" "$TEST_CONFIG" | grep -q "enabled = true"; then
    echo "ERROR: factory.toml quality_gates was not updated to enabled = true after --apply"
    exit 1
fi

# Verify SQLite optimization_events audit record was created
AUDIT_COUNT=$(sqlite3 "$TEST_DB" "SELECT COUNT(*) FROM optimization_events WHERE fingerprint = 'failure_class:db_lock' AND action_taken = 'hardened';")
if [ "$AUDIT_COUNT" -ne 1 ]; then
    echo "ERROR: Expected 1 audit event in optimization_events, found $AUDIT_COUNT"
    exit 1
fi

echo "==> Step 4: Verify idempotency on second --apply run..."
SECOND_APPLY_JSON=$($PA_BIN telemetry harden --config "$TEST_CONFIG" --apply --json)
SECOND_HAS_CHANGES=$(echo "$SECOND_APPLY_JSON" | jq -r '.has_changes')
if [ "$SECOND_HAS_CHANGES" != "false" ]; then
    echo "ERROR: Second run should have has_changes = false (idempotent), got $SECOND_HAS_CHANGES"
    exit 1
fi

echo "==> Step 5: Run OKR brief generation..."
BRIEF_JSON=$($PA_BIN okr brief --config "$TEST_CONFIG" --dir "$OKRS_DIR" --json)
echo "$BRIEF_JSON" | jq .

OBJ_COUNT=$(echo "$BRIEF_JSON" | jq -r '.total_objectives')
if [ "$OBJ_COUNT" -lt 1 ]; then
    echo "ERROR: Expected at least 1 objective in OKR brief, got $OBJ_COUNT"
    exit 1
fi

REPORT_FILE=$(echo "$BRIEF_JSON" | jq -r '.report_file')
if [ ! -f "$REPORT_FILE" ]; then
    echo "ERROR: Expected report file $REPORT_FILE to exist"
    exit 1
fi

# Verify markdown content in report file
grep -q "# OKR Progress & FinOps Risk Brief" "$REPORT_FILE"
grep -q "Enterprise Reliability & Hardening" "$REPORT_FILE"

# Verify optimization_events record for OKR brief
OKR_EVENT_COUNT=$(sqlite3 "$TEST_DB" "SELECT COUNT(*) FROM optimization_events WHERE action_taken = 'okr_brief_generated';")
if [ "$OKR_EVENT_COUNT" -ne 1 ]; then
    echo "ERROR: Expected 1 okr_brief_generated event in optimization_events, found $OKR_EVENT_COUNT"
    exit 1
fi

echo "=========================================================="
echo " SUCCESS: All Closed-Loop Self-Optimization E2E checks passed!"
echo "=========================================================="
