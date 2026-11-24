#!/usr/bin/env bash
# End-to-End Test for AST Component Drift Detection & Mobile Design Gates (iOS & Android)
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)
cd "$REPO_ROOT"

echo "=========================================================="
echo " PA-Container 2.0: E2E Design Drift & Mobile Gates"
echo " Platform: $(uname -s) ($(uname -m))"
echo "=========================================================="

export PA_TEST_MODE=1
export PA_DISABLE_KEYRING=1
PA_BIN="cargo run --quiet --bin pa --"

TMP_DIR=$(mktemp -d /tmp/pa-design-drift-test-XXXXXX)
TEST_CONFIG="$TMP_DIR/factory.toml"
TEST_DB="$TMP_DIR/factory.db"

cleanup() {
    rm -rf "$TMP_DIR"
}
trap cleanup EXIT

# Setup test workspace directories
TOKENS_DIR="$TMP_DIR/design/tokens"
CONTRACTS_DIR="$TMP_DIR/design/contracts"
WEB_SRC="$TMP_DIR/src"
IOS_SRC="$TMP_DIR/ios"
ANDROID_SRC="$TMP_DIR/app/src/main/java"
REPORTS_DIR="$TMP_DIR/.pa/reports"

mkdir -p "$TOKENS_DIR" "$CONTRACTS_DIR" "$WEB_SRC" "$IOS_SRC" "$ANDROID_SRC" "$REPORTS_DIR"

# 1. Setup Design Tokens (W3C DTCG)
cat <<'EOF' > "$TOKENS_DIR/tokens.json"
{
  "color": {
    "brand": {
      "primary": {
        "$value": "#2563eb",
        "$type": "color"
      }
    }
  },
  "spacing": {
    "sm": {
      "$value": "8px",
      "$type": "dimension"
    }
  }
}
EOF

# 2. Setup Component Contract for Button
cat <<'EOF' > "$CONTRACTS_DIR/button.toml"
name = "Button"
description = "Core button component"
platforms = ["web", "ios", "android"]
tokens = ["color.brand.primary", "spacing.sm"]

[web]
component = "src/ds/DSButton.tsx"

[ios]
component = "ios/DSButton.swift"

[android]
component = "app/src/main/java/DsButton.kt"
EOF

# 3. Setup factory.toml
cat <<EOF > "$TEST_CONFIG"
schema_version = "2.1"

[storage]
provider = "sqlite"
path = "$TEST_DB"

[design_system]
provider = "git_only"
tokens_path = "design/tokens/tokens.json"
contracts_path = "design/contracts"
platforms = ["web", "ios", "android"]
on_missing_platform = "skip"

[design_system.drift]
enabled = true
engine = "native"
flag_new_primitives = true
on_raw_primitive = "warn"
on_new_primitive = "needs_design_review"

[design_system.ios]
enabled = true
visual_diff_tool = "swift_snapshot"
max_visual_diff_pct = 0.05
on_missing_platform = "skip"

[design_system.android]
enabled = true
visual_diff_tool = "paparazzi"
max_visual_diff_pct = 0.05
on_missing_platform = "skip"
EOF

echo "--- Test 1: Compliant workspace with approved components and comments ---"
mkdir -p "$TMP_DIR/src/ds"
cat <<'EOF' > "$TMP_DIR/src/ds/DSButton.tsx"
// Design System Implementation file (must be ignored by drift)
export const DSButton = () => <button>Internal Button</button>;
EOF

cat <<'EOF' > "$WEB_SRC/App.tsx"
// Comment with raw <button> must be ignored
/* Block comment with <button> ignored */
export const App = () => {
    return <DSButton>Click</DSButton>;
};
EOF

REPORT_1=$(cd "$TMP_DIR" && $REPO_ROOT/target/debug/pa design check --config "$TEST_CONFIG" --json)
echo "$REPORT_1" | jq .

IS_COMPLIANT_1=$(echo "$REPORT_1" | jq -r '.is_compliant')
NEEDS_REVIEW_1=$(echo "$REPORT_1" | jq -r '.needs_design_review')

if [ "$IS_COMPLIANT_1" != "true" ]; then
    echo "FAILED: Expected compliant workspace in Test 1"
    exit 1
fi

if [ "$NEEDS_REVIEW_1" != "false" ]; then
    echo "FAILED: Expected needs_design_review = false in Test 1"
    exit 1
fi
echo "✓ Test 1 passed: Approved components and comments handled cleanly."

echo "--- Test 2: Raw primitive drift detection (<button>, Button) ---"
cat <<'EOF' > "$WEB_SRC/DriftView.tsx"
export const DriftView = () => {
    return <button onClick={() => {}}>Raw Web Button</button>;
};
EOF

cat <<'EOF' > "$IOS_SRC/DriftView.swift"
struct MyIosScreen: View {
    var body: some View {
        Button(action: {}) {
            Text("Raw iOS Button")
        }
    }
}
EOF

REPORT_2=$(cd "$TMP_DIR" && $REPO_ROOT/target/debug/pa design check --config "$TEST_CONFIG" --json)
RAW_VIOLATIONS_COUNT=$(echo "$REPORT_2" | jq '[.violations[] | select(.rule == "raw_primitive_violation")] | length')
echo "Detected raw primitive violations: $RAW_VIOLATIONS_COUNT"

if [ "$RAW_VIOLATIONS_COUNT" -lt 2 ]; then
    echo "FAILED: Expected at least 2 raw primitive violations in Test 2, found $RAW_VIOLATIONS_COUNT"
    exit 1
fi
echo "✓ Test 2 passed: Raw primitives flagged."

echo "--- Test 3: Unregistered UI component triggers needs_design_review = true ---"
cat <<'EOF' > "$WEB_SRC/NewCard.tsx"
export const CustomCard = () => {
    return <div>Card Content</div>;
};
EOF

REPORT_3=$(cd "$TMP_DIR" && $REPO_ROOT/target/debug/pa design check --config "$TEST_CONFIG" --json)
NEEDS_REVIEW_3=$(echo "$REPORT_3" | jq -r '.needs_design_review')
NEW_COMPS_3=$(echo "$REPORT_3" | jq -r '.new_components | join(",")')
echo "needs_design_review: $NEEDS_REVIEW_3, new_components: $NEW_COMPS_3"

if [ "$NEEDS_REVIEW_3" != "true" ]; then
    echo "FAILED: Expected needs_design_review = true in Test 3"
    exit 1
fi

if [[ "$NEW_COMPS_3" != *"CustomCard"* ]]; then
    echo "FAILED: Expected CustomCard in new_components list"
    exit 1
fi
echo "✓ Test 3 passed: Unregistered component flagged for design review."

echo "--- Test 4: SQLite Persistence of Design Gate Results ---"
if [ ! -f "$TEST_DB" ]; then
    echo "FAILED: factory.db was not created"
    exit 1
fi

DB_ROWS=$(sqlite3 "$TEST_DB" "SELECT platform, raw_primitive_violations, needs_design_review, status FROM design_gate_results;")
echo "Database records in design_gate_results:"
echo "$DB_ROWS"

if [ -z "$DB_ROWS" ]; then
    echo "FAILED: No rows inserted into design_gate_results table"
    exit 1
fi
echo "✓ Test 4 passed: SQLite persistence verified."

echo "--- Test 5: Per-Platform filtering flag (--platform ios) ---"
REPORT_IOS=$(cd "$TMP_DIR" && $REPO_ROOT/target/debug/pa design check --config "$TEST_CONFIG" --platform ios --json)
CHECKED_PLATFORMS=$(echo "$REPORT_IOS" | jq -r '.platform_results | keys | join(",")')
echo "Checked platforms: $CHECKED_PLATFORMS"

if [ "$CHECKED_PLATFORMS" != "ios" ]; then
    echo "FAILED: Expected only 'ios' platform result, found: $CHECKED_PLATFORMS"
    exit 1
fi
echo "✓ Test 5 passed: Platform filtering verified."

echo "=========================================================="
echo " All E2E Design Drift & Mobile Gate Tests PASSED!"
echo "=========================================================="
