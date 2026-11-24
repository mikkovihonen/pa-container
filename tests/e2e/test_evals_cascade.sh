#!/usr/bin/env bash
# End-to-End Automated LLM Evals & Cascade Verification Test
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)
cd "$REPO_ROOT"

echo "=========================================================="
echo " PA-Container 2.0: E2E Automated LLM Evals Verification"
echo " Platform: $(uname -s) ($(uname -m))"
echo "=========================================================="

export PA_TEST_MODE=1
export PA_DISABLE_KEYRING=1
PA_BIN="cargo run --quiet --bin pa --"

TMP_DIR=$(mktemp -d /tmp/pa-eval-test-XXXXXX)
TEST_CONFIG="$TMP_DIR/factory.toml"
TEST_DB="$TMP_DIR/factory.db"

# Cleanup on exit
cleanup() {
    if [ -n "${S1_PID:-}" ]; then
        kill "$S1_PID" >/dev/null 2>&1 || true
        wait "$S1_PID" 2>/dev/null || true
    fi
    if [ -n "${S2_PID:-}" ]; then
        kill "$S2_PID" >/dev/null 2>&1 || true
        wait "$S2_PID" 2>/dev/null || true
    fi
    rm -rf "$TMP_DIR"
}
trap cleanup EXIT

# 1. Start Mock System 1 Decision Server on port 8191
python3 -c '
import http.server
import json
import socketserver

class S1Handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        content_len = int(self.headers.get("Content-Length", 0))
        post_body = self.rfile.read(content_len)
        data = json.loads(post_body)
        task_id = data.get("state", {}).get("task_id", "")
        
        # If task is feat-eval-02, return low confidence to trigger cascade
        if "feat-eval-02" in task_id:
            res = {
                "results": [
                    {"id": "req_completeness", "score": 0.70, "confidence": 0.60, "finding": "Borderline coverage"},
                    {"id": "scope_fidelity", "score": 0.75, "confidence": 0.65},
                    {"id": "edge_cases_handled", "score": 0.60, "confidence": 0.55}
                ],
                "cost_usd": 0.0002
            }
        else:
            # High confidence pass
            res = {
                "results": [
                    {"id": "req_completeness", "score": 0.95, "confidence": 0.95, "finding": "Fully satisfied"},
                    {"id": "scope_fidelity", "score": 0.90, "confidence": 0.92},
                    {"id": "edge_cases_handled", "score": 0.85, "confidence": 0.88}
                ],
                "cost_usd": 0.0002
            }
        
        body = json.dumps(res).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass

socketserver.TCPServer.allow_reuse_address = True
with socketserver.TCPServer(("127.0.0.1", 8191), S1Handler) as httpd:
    httpd.serve_forever()
' &
S1_PID=$!

# 2. Start Mock System 2 LLM Judge Server on port 8192
python3 -c '
import http.server
import json
import socketserver

class S2Handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        content_len = int(self.headers.get("Content-Length", 0))
        post_body = self.rfile.read(content_len)
        
        llm_reply = {
            "score": 0.89,
            "confidence": 0.93,
            "passed": True,
            "items": [
                {"id": "req_completeness", "score": 0.92, "confidence": 0.95, "passed": True, "finding": "Confirmed all items in diff"},
                {"id": "scope_fidelity", "score": 0.90, "confidence": 0.92, "passed": True, "finding": "Clean scope adherence"},
                {"id": "edge_cases_handled", "score": 0.85, "confidence": 0.90, "passed": True, "finding": "Adequate error guards"}
            ],
            "rationale": "System 2 generative deep analysis confirmed complete requirement coverage and error handling.",
            "cost_usd": 0.004
        }
        
        res = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(llm_reply)
                    }
                }
            ]
        }
        
        body = json.dumps(res).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass

socketserver.TCPServer.allow_reuse_address = True
with socketserver.TCPServer(("127.0.0.1", 8192), S2Handler) as httpd:
    httpd.serve_forever()
' &
S2_PID=$!

# Wait for mock servers to bind
sleep 1

# 3. Create test factory.toml
cat <<EOF > "$TEST_CONFIG"
schema_version = "2.1"

[storage]
path = "$TEST_DB"

[telemetry.otlp]
provider = "none"

[evals]
enabled = true
mode = "cascade"
rubrics_dir = "docs/evals/rubrics"
min_pass_score = 0.80
block_on_fail = true
escalate_to_system2_below_confidence = 0.80
escalate_on_fail_for_rationale = true
fence_untrusted_diffs = true
enforce_distinct_model_family = true

[evals.system1]
provider = "decision_http"
endpoint = "http://127.0.0.1:8191/v1/decide"
model = "typesafe-jev-v1"

[evals.system2]
provider = "openai_compat"
endpoint = "http://127.0.0.1:8192/v1/chat/completions"
model = "qwen2.5-coder-32b"
temperature = 0.0
EOF

echo "==> Step 1: Testing High-Confidence Evaluation (Stops at Stage 1)..."
OUT_T1=$($PA_BIN eval run --task "feat-eval-01" --rubric "spec_adherence" --config "$TEST_CONFIG")
echo "$OUT_T1"
if ! echo "$OUT_T1" | grep -q "Rubric 'spec_adherence' \[system1\]"; then
    echo "ERROR: Expected feat-eval-01 to resolve at stage 'system1'" >&2
    exit 1
fi
if echo "$OUT_T1" | grep -q "Escalated: true"; then
    echo "ERROR: feat-eval-01 should not have escalated to System 2" >&2
    exit 1
fi
echo "Verified: feat-eval-01 passed cleanly at Stage 1 (system1)."

echo "==> Step 2: Testing Low-Confidence Cascade Escalation (System 1 -> System 2)..."
OUT_T2=$($PA_BIN eval run --task "feat-eval-02" --rubric "spec_adherence" --config "$TEST_CONFIG")
echo "$OUT_T2"
if ! echo "$OUT_T2" | grep -q "Rubric 'spec_adherence' \[cascade\]"; then
    echo "ERROR: Expected feat-eval-02 to escalate to stage 'cascade'" >&2
    exit 1
fi
if ! echo "$OUT_T2" | grep -q "Escalated: true"; then
    echo "ERROR: feat-eval-02 should have escalated to System 2" >&2
    exit 1
fi
echo "Verified: feat-eval-02 successfully escalated to Stage 2 (cascade) due to confidence below 0.80."

echo "==> Step 3: Verifying SQLite Persistence and Calibration Report..."
REPORT_TEXT=$($PA_BIN eval report --config "$TEST_CONFIG")
echo "$REPORT_TEXT"
if ! echo "$REPORT_TEXT" | grep -q "Total Evaluations: *2"; then
    echo "ERROR: Expected total evaluations to be 2 in report" >&2
    exit 1
fi
if ! echo "$REPORT_TEXT" | grep -q "System 2 Escalations: 50.0%"; then
    echo "ERROR: Expected escalation rate to be 50.0%" >&2
    exit 1
fi
echo "Verified: Human-readable report displays correct calibration metrics."

echo "==> Step 4: Verifying JSON Output Report..."
REPORT_JSON=$($PA_BIN eval report --config "$TEST_CONFIG" --json)
echo "$REPORT_JSON"
if ! echo "$REPORT_JSON" | grep -q '"total_evals": 2'; then
    echo "ERROR: Expected total_evals = 2 in JSON report" >&2
    exit 1
fi
if ! echo "$REPORT_JSON" | grep -q '"escalation_rate": 0.5'; then
    echo "ERROR: Expected escalation_rate = 0.5 in JSON report" >&2
    exit 1
fi

echo "=========================================================="
echo " SUCCESS: All Automated LLM Evals verification steps passed!"
echo "=========================================================="
