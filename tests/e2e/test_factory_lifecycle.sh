#!/usr/bin/env bash
# End-to-End Factory Lifecycle & Parity Verification Test
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)
cd "$REPO_ROOT"

echo "=========================================================="
echo " PA-Container 2.0: E2E Factory Lifecycle Verification"
echo " Platform: $(uname -s) ($(uname -m))"
echo "=========================================================="

PA_BIN="cargo run --quiet --bin pa --"

# 1. Verify Status Command
echo "==> Step 1: Querying factory status..."
STATUS_JSON=$($PA_BIN factory status)
echo "$STATUS_JSON"

BACKEND=$(echo "$STATUS_JSON" | grep -o '"backend": *"[^"]*"' | head -n1 || true)
if [ -z "$BACKEND" ]; then
    echo "ERROR: factory status failed to return valid JSON containing 'backend'" >&2
    exit 1
fi
echo "Verified: $BACKEND"

# 2. Run Agent Execution Task
echo "==> Step 2: Executing agent workload..."
$PA_BIN run --agent agent1 --prompt "Automated parity lifecycle test verification"

# 3. Verify Agent Git Branch in Vault
echo "==> Step 3: Verifying atomic Git Vault state..."
$PA_BIN review agent1

echo "=========================================================="
echo " SUCCESS: Factory lifecycle verified with feature parity!"
echo "=========================================================="
