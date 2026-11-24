#!/usr/bin/env bash
# End-to-End Test for Optional Penpot Stack & DTCG Token Compiler
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)
cd "$REPO_ROOT"

echo "=========================================================="
echo " PA-Container 2.0: E2E Penpot & DTCG Token Compiler"
echo " Platform: $(uname -s) ($(uname -m))"
echo "=========================================================="

export PA_TEST_MODE=1
export PA_DISABLE_KEYRING=1
PA_BIN="cargo run --quiet --bin pa --"

TMP_DIR=$(mktemp -d /tmp/pa-design-e2e-XXXXXX)
cleanup() {
    rm -rf "$TMP_DIR"
}
trap cleanup EXIT

echo "==> Step 1: Validate deploy/penpot/compose.yaml syntax and services"
COMPOSE_FILE="$REPO_ROOT/deploy/penpot/compose.yaml"
test -f "$COMPOSE_FILE"

grep -q "penpot-frontend" "$COMPOSE_FILE"
grep -q "penpot-backend" "$COMPOSE_FILE"
grep -q "penpot-exporter" "$COMPOSE_FILE"
grep -q "penpot-postgres" "$COMPOSE_FILE"
grep -q "penpot-valkey" "$COMPOSE_FILE"
grep -q "127.0.0.1:9001:8080" "$COMPOSE_FILE"

if command -v podman &>/dev/null; then
    echo "Validating syntax with podman compose..."
    podman compose -f "$COMPOSE_FILE" config > /dev/null || podman-compose -f "$COMPOSE_FILE" config > /dev/null || true
elif command -v docker &>/dev/null; then
    docker compose -f "$COMPOSE_FILE" config > /dev/null || true
fi
echo "[PASS] Step 1: Penpot compose stack verified"

echo "==> Step 2: Test 'pa design ui --url'"
UI_URL=$($PA_BIN design ui --url)
echo "Resolved Penpot UI URL: $UI_URL"
test "$UI_URL" = "http://127.0.0.1:9001"
echo "[PASS] Step 2: Penpot UI URL verified"

echo "==> Step 3: Test 'pa design compile' (code generation)"
COMPILE_JSON=$($PA_BIN design compile --json)
echo "$COMPILE_JSON"
python3 -c '
import json, sys
data = json.loads(sys.argv[1])
assert data["status"] == "success"
assert data["tool"] == "style_dictionary"
assert len(data["generated_files"]) == 3
assert "src/styles/tokens.css" in data["generated_files"]
assert "Sources/DesignSystem/Tokens.swift" in data["generated_files"]
assert "app/src/main/java/com/example/ui/Tokens.kt" in data["generated_files"]
' "$COMPILE_JSON"

test -f "src/styles/tokens.css"
test -f "Sources/DesignSystem/Tokens.swift"
test -f "app/src/main/java/com/example/ui/Tokens.kt"

grep -q "\-\-color-brand-primary" "src/styles/tokens.css"
grep -q "colorBrandPrimary" "Sources/DesignSystem/Tokens.swift"
grep -q "COLOR_BRAND_PRIMARY" "app/src/main/java/com/example/ui/Tokens.kt"
echo "[PASS] Step 3: Platform tokens generated and verified"

echo "==> Step 4: Test 'pa design compile --check'"
CHECK_JSON=$($PA_BIN design compile --check --json)
echo "$CHECK_JSON"
python3 -c '
import json, sys
data = json.loads(sys.argv[1])
assert data["is_fresh"] is True
assert len(data["missing_files"]) == 0
assert len(data["stale_files"]) == 0
' "$CHECK_JSON"
echo "[PASS] Step 4: Token freshness check verified"

echo "==> Step 5: Test 'pa design check' integration & stale token gate failure"
CHECK_REPORT=$($PA_BIN design check --json)
python3 -c '
import json, sys
data = json.loads(sys.argv[1])
assert data["is_compliant"] is True
assert data["platform_results"]["compiler"]["status"] == "passed"
' "$CHECK_REPORT"

# Simulate token staleness by removing one output file
rm -f "src/styles/tokens.css"

set +e
FAILED_CHECK=$($PA_BIN design check --json 2>/dev/null)
EXIT_CODE=$?
set -e

test $EXIT_CODE -ne 0
python3 -c '
import json, sys
data = json.loads(sys.argv[1])
assert data["is_compliant"] is False
assert data["platform_results"]["compiler"]["status"] == "failed"
' "$FAILED_CHECK"

# Restore by compiling
$PA_BIN design compile --json > /dev/null
test -f "src/styles/tokens.css"

RESTORED_CHECK=$($PA_BIN design check --json)
python3 -c '
import json, sys
data = json.loads(sys.argv[1])
assert data["is_compliant"] is True
' "$RESTORED_CHECK"
echo "[PASS] Step 5: Gate freshness enforcement and recovery verified"

echo "=========================================================="
echo " ALL E2E TESTS PASSED SUCCESSFULLY! "
echo "=========================================================="
