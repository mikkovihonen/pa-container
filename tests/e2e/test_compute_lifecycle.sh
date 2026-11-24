#!/usr/bin/env bash
# End-to-End Test for Compute Plane Lifecycle Supervision (llama-server in pa factory up/down)
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)
cd "$REPO_ROOT"

echo "=========================================================="
echo " PA-Container 2.0: E2E Compute Plane Lifecycle Supervision"
echo " Platform: $(uname -s) ($(uname -m))"
echo "=========================================================="

export PA_TEST_MODE=1
export PA_DISABLE_KEYRING=1
PA_BIN="cargo run --quiet --bin pa --"

TMP_DIR=$(mktemp -d /tmp/pa-compute-test-XXXXXX)
TEST_CONFIG="$TMP_DIR/factory.toml"
TEST_CONFIG2="$TMP_DIR/factory2.toml"
STATE_DIR="$TMP_DIR/state"
LOG_DIR="$TMP_DIR/logs"
BIN_DIR="$TMP_DIR/bin"

export PA_COMPUTE_STATE_DIR="$STATE_DIR"
export PA_COMPUTE_LOG_DIR="$LOG_DIR"
export PA_COMPUTE_BIN_DIR="$BIN_DIR"

cleanup() {
    # Terminate any remaining background processes
    pkill -f "$BIN_DIR/mock_llama_server.py" 2>/dev/null || true
    rm -rf "$TMP_DIR"
}
trap cleanup EXIT

mkdir -p "$STATE_DIR" "$LOG_DIR" "$BIN_DIR"

# 1. Choose an available local port
TEST_PORT=$(python3 -c '
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.bind(("127.0.0.1", 0))
port = s.getsockname()[1]
s.close()
print(port)
')

# 2. Create mock llama-server python script
cat <<'EOF' > "$BIN_DIR/mock_llama_server.py"
import sys, http.server, time

CALLS = [0]
class MockHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        CALLS[0] += 1
        if CALLS[0] < 3:
            self.send_response(503)
            self.end_headers()
        else:
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
    def log_message(self, format, *args):
        pass

port = int(sys.argv[sys.argv.index('--port') + 1])
server = http.server.HTTPServer(('127.0.0.1', port), MockHandler)
server.serve_forever()
EOF

cat <<EOF > "$BIN_DIR/llama-server"
#!/bin/sh
exec python3 "$BIN_DIR/mock_llama_server.py" "\$@"
EOF
chmod +x "$BIN_DIR/llama-server"

# 3. Create factory.toml with compute.llama_server configured
cat <<EOF > "$TEST_CONFIG"
schema_version = "2.1"

[factory]
name = "factory-alpha"

[compute]
backend = "auto"

[compute.llama_server]
enabled = true
managed_lifecycle = true
binary_path = "$BIN_DIR/llama-server"
host = "127.0.0.1"
port = $TEST_PORT
ctx_size = 32768
gpu_layers = -1
startup_timeout_sec = 10
on_missing_binary = "block"
EOF

# Clone config for session 2 sharing the exact same compute spec
cat <<EOF > "$TEST_CONFIG2"
schema_version = "2.1"

[factory]
name = "factory-beta"

[compute]
backend = "auto"

[compute.llama_server]
enabled = true
managed_lifecycle = true
binary_path = "$BIN_DIR/llama-server"
host = "127.0.0.1"
port = $TEST_PORT
ctx_size = 32768
gpu_layers = -1
startup_timeout_sec = 10
on_missing_binary = "block"
EOF

echo "==> Step 1: Verify initial stopped status"
STATUS_OUTPUT=$($PA_BIN factory status --config "$TEST_CONFIG")
echo "$STATUS_OUTPUT" | grep -q '"compute_plane"' || {
    echo "ERROR: compute_plane section missing from factory status JSON."
    exit 1
}
echo "$STATUS_OUTPUT" | grep -q '"status": "stopped"' || {
    echo "ERROR: Expected initial status to be stopped."
    exit 1
}
echo "    [PASS] Factory status accurately reports stopped compute plane."

echo "==> Step 2: Bring UP factory session 1 (ensure llama-server starts)"
UP_OUTPUT=$($PA_BIN factory up --config "$TEST_CONFIG")
echo "$UP_OUTPUT" | grep -q "Compute Plane: llama-server running" || {
    echo "ERROR: factory up did not confirm running llama-server."
    echo "$UP_OUTPUT"
    exit 1
}
echo "    [PASS] Session 1 spawned and verified llama-server."

echo "==> Step 3: Verify running status, healthy endpoint, and state file"
STATUS_RUNNING=$($PA_BIN factory status --config "$TEST_CONFIG")
echo "$STATUS_RUNNING" | grep -q '"status": "running"' || {
    echo "ERROR: factory status did not report running."
    exit 1
}
echo "$STATUS_RUNNING" | grep -q '"health": "healthy"' || {
    echo "ERROR: factory status did not report healthy."
    exit 1
}
echo "$STATUS_RUNNING" | grep -q '"refcount": 1' || {
    echo "ERROR: refcount was not 1."
    exit 1
}
STATE_FILES=("$STATE_DIR"/*.json)
[ -f "${STATE_FILES[0]}" ] || {
    echo "ERROR: State file was not created in $STATE_DIR"
    exit 1
}
echo "    [PASS] Status reports running, healthy, refcount 1 with state file present."

echo "==> Step 4: Bring UP factory session 2 (verify shared refcount increments to 2)"
UP_OUTPUT2=$($PA_BIN factory up --config "$TEST_CONFIG2")
echo "$UP_OUTPUT2" | grep -q "refcount: 2" || {
    echo "ERROR: factory up session 2 did not increment refcount to 2."
    echo "$UP_OUTPUT2"
    exit 1
}
STATUS_MULTI=$($PA_BIN factory status --config "$TEST_CONFIG")
echo "$STATUS_MULTI" | grep -q '"refcount": 2' || {
    echo "ERROR: Status did not report refcount 2."
    exit 1
}
echo "    [PASS] Session 2 attached to existing llama-server process (refcount = 2)."

echo "==> Step 5: Shut down session 1 (verify process retained, refcount drops to 1)"
DOWN_OUTPUT1=$($PA_BIN factory down --config "$TEST_CONFIG")
echo "$DOWN_OUTPUT1" | grep -q "llama-server retained (1 active session(s) remain)" || {
    echo "ERROR: Session 1 down did not retain process."
    echo "$DOWN_OUTPUT1"
    exit 1
}
STATUS_AFTER_REL1=$($PA_BIN factory status --config "$TEST_CONFIG2")
echo "$STATUS_AFTER_REL1" | grep -q '"refcount": 1' || {
    echo "ERROR: Status refcount did not drop to 1."
    exit 1
}
echo "    [PASS] Releasing session 1 retained process with refcount 1."

echo "==> Step 6: Shut down session 2 (verify process terminates and state is cleaned)"
DOWN_OUTPUT2=$($PA_BIN factory down --config "$TEST_CONFIG2")
echo "$DOWN_OUTPUT2" | grep -q "terminated" || {
    echo "ERROR: Session 2 down did not terminate llama-server."
    echo "$DOWN_OUTPUT2"
    exit 1
}
STATUS_FINAL=$($PA_BIN factory status --config "$TEST_CONFIG")
echo "$STATUS_FINAL" | grep -q '"status": "stopped"' || {
    echo "ERROR: Status after final shutdown did not report stopped."
    exit 1
}
# State file should be deleted
shopt -s nullglob
REMAINING_STATE=("$STATE_DIR"/*.json)
shopt -u nullglob
if [ ${#REMAINING_STATE[@]} -ne 0 ]; then
    echo "ERROR: State file was not deleted upon final termination."
    exit 1
fi
echo "    [PASS] Releasing final session cleanly terminated process and pruned state file."

echo "==> Step 7: Verify --keep-compute preserves server on factory down"
$PA_BIN factory up --config "$TEST_CONFIG" > /dev/null
KEEP_DOWN_OUTPUT=$($PA_BIN factory down --keep-compute --config "$TEST_CONFIG")
echo "$KEEP_DOWN_OUTPUT" | grep -F -q -e "--keep-compute specified, leaving inference server running" || {
    echo "ERROR: --keep-compute was not respected."
    exit 1
}
STATUS_KEEP=$($PA_BIN factory status --config "$TEST_CONFIG")
echo "$STATUS_KEEP" | grep -q '"status": "running"' || {
    echo "ERROR: llama-server was terminated despite --keep-compute."
    exit 1
}

# Clean up with --force
FORCE_DOWN_OUTPUT=$($PA_BIN factory down --force --config "$TEST_CONFIG")
echo "$FORCE_DOWN_OUTPUT" | grep -q "terminated" || {
    echo "ERROR: --force did not terminate llama-server."
    exit 1
}
echo "    [PASS] --keep-compute and --force flags verified successfully."

echo "=========================================================="
echo " [SUCCESS] All E2E Compute Plane Lifecycle Tests Passed!"
echo "=========================================================="
