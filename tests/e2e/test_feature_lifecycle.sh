#!/usr/bin/env bash
# End-to-End Feature Implementation Lifecycle Verification Test
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)
cd "$REPO_ROOT"

echo "=========================================================="
echo " PA-Container 2.0: E2E Feature Lifecycle Verification"
echo " Platform: $(uname -s) ($(uname -m))"
echo "=========================================================="

# Non-interactive test credential overrides (ensures zero OS Keychain/keyring prompts)
export PA_TEST_MODE=1
export PA_DISABLE_KEYRING=1
export ADMIN_PASSWORD="pa-test-admin-password"
export OPENAI_API_KEY="test-mock-openai-key"
export GEMINI_API_KEY="test-mock-gemini-key"
export ANTHROPIC_API_KEY="test-mock-anthropic-key"

PA_BIN="cargo run --quiet --bin pa --"
TEST_FEATURE="e2e-auth-lifecycle"
ORIGINAL_HEAD=$(git rev-parse HEAD)

cleanup() {
    rm -rf ".pa/features/$TEST_FEATURE"
    rm -rf ".pa/review/feature-$TEST_FEATURE"
    if [ -n "$ORIGINAL_HEAD" ]; then
        git reset "$ORIGINAL_HEAD" >/dev/null 2>&1 || true
    fi
}
trap cleanup EXIT

# Cleanup any previous artifact
rm -rf ".pa/features/$TEST_FEATURE"

# 1. Phase 1: Planning & Specification (Gate 1)
echo "==> Step 1: Planning feature with Architect (Gate 1 sign-off)..."
$PA_BIN feature plan "$TEST_FEATURE" \
    --title "E2E Authentication Lifecycle" \
    --prompt "Implement zero-trust OAuth2 token cache with visual verification" \
    --approve \
    --non-interactive

# Verify spec files exist
if [ ! -f ".pa/features/$TEST_FEATURE/spec.md" ] || \
   [ ! -f ".pa/features/$TEST_FEATURE/tasks.md" ] || \
   [ ! -f ".pa/features/$TEST_FEATURE/test_plan.md" ]; then
    echo "ERROR: Feature planning failed to generate required specification files" >&2
    exit 1
fi
echo "Verified: spec.md, tasks.md, and test_plan.md exist in .pa/features/$TEST_FEATURE/"

# 2. Status inspection
echo "==> Step 2: Querying feature status..."
STATUS_OUTPUT=$($PA_BIN feature status "$TEST_FEATURE")
echo "$STATUS_OUTPUT"
if ! echo "$STATUS_OUTPUT" | grep -q "Status: *approved"; then
    echo "ERROR: Feature status is not 'approved' after Gate 1 sign-off" >&2
    exit 1
fi

# 3. Phase 2-4: Staged Multi-Tenant Pipeline (Red -> Green -> Verify)
echo "==> Step 3: Executing staged multi-agent pipeline..."
$PA_BIN feature run "$TEST_FEATURE"

# Verify evidence directory
if [ ! -f ".pa/features/$TEST_FEATURE/evidence/verification.log" ]; then
    echo "ERROR: Missing verification evidence log in .pa/features/$TEST_FEATURE/evidence/" >&2
    exit 1
fi
echo "Verified: Verification evidence captured."

# 4. Phase 5: Review & Gate 2 Approval
echo "==> Step 4: Reviewing feature worktree and evidence..."
$PA_BIN feature review "$TEST_FEATURE"

echo "==> Step 5: Gate 2: Approving and merging feature..."
$PA_BIN feature review "$TEST_FEATURE" --approve

# Verify status is merged
STATUS_JSON=$($PA_BIN feature status "$TEST_FEATURE" --json)
if ! echo "$STATUS_JSON" | grep -q '"status": "merged"'; then
    echo "ERROR: Feature status did not transition to 'merged' after approval" >&2
    exit 1
fi
echo "Verified: Feature successfully merged into target branch."

# Cleanup test feature
rm -rf ".pa/features/$TEST_FEATURE"

echo "=========================================================="
echo " SUCCESS: End-to-end Feature Lifecycle verified!"
echo "=========================================================="
