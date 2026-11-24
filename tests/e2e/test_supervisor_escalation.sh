#!/usr/bin/env bash
# End-to-End Concurrent Host Supervisor & Work Queue Verification Test
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)
cd "$REPO_ROOT"

echo "=========================================================="
echo " PA-Container 2.0: E2E Supervisor & Work Queue Verification"
echo " Platform: $(uname -s) ($(uname -m))"
echo "=========================================================="

export PA_TEST_MODE=1
export PA_DISABLE_KEYRING=1
PA_BIN="cargo run --quiet --bin pa --"

cleanup() {
    # Ensure supervisor daemon is stopped if running
    $PA_BIN supervisor stop >/dev/null 2>&1 || true
    rm -f .pa/supervisor.sock .pa/supervisor.pid
    rm -rf .pa/intercom/inbox/test-worker
}
trap cleanup EXIT

echo "==> Step 1: Initial Supervisor Status (Offline mode)..."
STATUS_OFFLINE=$($PA_BIN supervisor status)
echo "$STATUS_OFFLINE"
if ! echo "$STATUS_OFFLINE" | grep -q "Daemon State: *OFFLINE"; then
    echo "ERROR: Expected supervisor to be OFFLINE initially" >&2
    exit 1
fi
echo "Verified: Supervisor reported OFFLINE correctly."

echo "==> Step 2: Enqueueing concurrent tasks in work queue..."
$PA_BIN task enqueue --role "feature" --task-id "task-e2e-esc-01" --req "REQ-AUTH-01" --kr "KR-OPS-01" --priority 100 --tier "local"
$PA_BIN task enqueue --role "feature" --task-id "task-e2e-esc-02" --req "REQ-AUTH-02" --kr "KR-OPS-01" --priority 50 --tier "local"
$PA_BIN task enqueue --role "review_assist" --task-id "task-e2e-esc-03" --req "REQ-AUTH-03" --kr "KR-OPS-02" --priority 10 --tier "local"

echo "==> Step 3: Querying task queue..."
QUEUE_LIST=$($PA_BIN task list)
echo "$QUEUE_LIST"
if ! echo "$QUEUE_LIST" | grep -q "task-e2e-esc-01" || \
   ! echo "$QUEUE_LIST" | grep -q "task-e2e-esc-02" || \
   ! echo "$QUEUE_LIST" | grep -q "task-e2e-esc-03"; then
    echo "ERROR: Missing enqueued tasks in task list" >&2
    exit 1
fi
echo "Verified: All 3 tasks present in work queue."

echo "==> Step 4: Starting Host Supervisor daemon (concurrency: 2)..."
$PA_BIN supervisor start --daemon --concurrency 2

# Wait for supervisor daemon to initialize socket
for i in {1..20}; do
    if [ -S ".pa/supervisor.sock" ]; then
        break
    fi
    sleep 0.2
done

if [ ! -S ".pa/supervisor.sock" ]; then
    echo "ERROR: Supervisor socket .pa/supervisor.sock was not created" >&2
    exit 1
fi

echo "==> Step 5: Querying active Supervisor status over IPC..."
STATUS_ONLINE=$($PA_BIN supervisor status)
echo "$STATUS_ONLINE"
if ! echo "$STATUS_ONLINE" | grep -q "Daemon State: *ONLINE"; then
    echo "ERROR: Expected supervisor to report ONLINE over IPC socket" >&2
    exit 1
fi

STATUS_JSON=$($PA_BIN supervisor status --json)
if ! echo "$STATUS_JSON" | grep -q '"running": true'; then
    echo "ERROR: Supervisor status JSON does not indicate running = true" >&2
    exit 1
fi
echo "Verified: Host Supervisor is running and reachable over IPC."

echo "==> Step 6: Testing Mid-Turn HITL Pause via agentintercom..."
mkdir -p .pa/intercom/inbox/test-worker
cat << 'EOF' > .pa/intercom/inbox/test-worker/pause.json
{
  "type": "hitl_pause",
  "task_id": "task-e2e-esc-02",
  "prompt": "Review required for external API integration"
}
EOF

# Give supervisor scheduler tick time to process the HITL message
sleep 1.5

STATUS_AWAITING=$($PA_BIN task list)
echo "$STATUS_AWAITING"
if ! echo "$STATUS_AWAITING" | grep "task-e2e-esc-02" | grep -q "awaiting_human"; then
    echo "ERROR: Task 'task-e2e-esc-02' did not transition to awaiting_human on HITL pause" >&2
    exit 1
fi
echo "Verified: Task transitioned to 'awaiting_human' and released slot."

echo "==> Step 7: Testing Task Resumption..."
$PA_BIN task resume "task-e2e-esc-02" --response "Approval granted to proceed with API integration."
STATUS_RESUMED=$($PA_BIN task list)
echo "$STATUS_RESUMED"
if echo "$STATUS_RESUMED" | grep "task-e2e-esc-02" | grep -q "awaiting_human"; then
    echo "ERROR: Task 'task-e2e-esc-02' remained in awaiting_human after resumption" >&2
    exit 1
fi
echo "Verified: Task resumed successfully and re-queued."

echo "==> Step 8: Testing Task Cancellation..."
$PA_BIN task cancel "task-e2e-esc-03"
STATUS_CANCELLED=$($PA_BIN task list)
if ! echo "$STATUS_CANCELLED" | grep "task-e2e-esc-03" | grep -q "cancelled"; then
    echo "ERROR: Task 'task-e2e-esc-03' was not marked as cancelled" >&2
    exit 1
fi
echo "Verified: Task cancelled and removed from active scheduling."

echo "==> Step 9: Stopping Host Supervisor daemon..."
$PA_BIN supervisor stop
sleep 1

if [ -S ".pa/supervisor.sock" ]; then
    echo "ERROR: Supervisor socket was not cleaned up after stop" >&2
    exit 1
fi

STATUS_FINAL=$($PA_BIN supervisor status)
if ! echo "$STATUS_FINAL" | grep -q "Daemon State: *OFFLINE"; then
    echo "ERROR: Expected supervisor to be OFFLINE after stopping" >&2
    exit 1
fi
echo "Verified: Supervisor stopped cleanly and cleaned up IPC socket."

# Cleanup test tasks
$PA_BIN task cancel "task-e2e-esc-01" >/dev/null 2>&1 || true
$PA_BIN task cancel "task-e2e-esc-02" >/dev/null 2>&1 || true

echo "=========================================================="
echo " SUCCESS: Supervisor and Work Queue E2E flow verified!"
echo "=========================================================="
