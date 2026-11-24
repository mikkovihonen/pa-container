#!/usr/bin/env bash
# End-to-End Test for Cross-Agent Skill Compiler (crates/pa-core and pa-cli)
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)
cd "$REPO_ROOT"

echo "=========================================================="
echo " PA-Container 2.0: E2E Cross-Agent Skill Compiler"
echo " Platform: $(uname -s) ($(uname -m))"
echo "=========================================================="

export PA_TEST_MODE=1
export PA_DISABLE_KEYRING=1
PA_BIN="cargo run --quiet --bin pa --"

TMP_DIR=$(mktemp -d /tmp/pa-skills-e2e-XXXXXX)
cleanup() {
    rm -rf "$TMP_DIR"
}
trap cleanup EXIT

STAGING_DIR="$TMP_DIR/staging"
mkdir -p "$STAGING_DIR"

echo "==> Step 1: Verify registered drivers (text and JSON)"
DRIVERS_OUT=$($PA_BIN skills drivers)
echo "$DRIVERS_OUT"
echo "$DRIVERS_OUT" | grep -q "pi"
echo "$DRIVERS_OUT" | grep -q "claude"
echo "$DRIVERS_OUT" | grep -q "opencode"
echo "$DRIVERS_OUT" | grep -q "antigravity"

DRIVERS_JSON=$($PA_BIN skills drivers --json)
python3 -c '
import json, sys
data = json.loads(sys.argv[1])
ids = [d["id"] for d in data]
assert "pi" in ids, "Missing pi"
assert "claude" in ids, "Missing claude"
assert "opencode" in ids, "Missing opencode"
assert "antigravity" in ids, "Missing antigravity"
' "$DRIVERS_JSON"
echo "[PASS] Step 1: Driver registry verified"

echo "==> Step 2: Verify repository skill bundles & role definitions"
VERIFY_OUT=$($PA_BIN skills verify)
echo "$VERIFY_OUT"
echo "$VERIFY_OUT" | grep -q "Total Discovered Skills: 30"
echo "$VERIFY_OUT" | grep -q "Verification Status: PASSED"

VERIFY_JSON=$($PA_BIN skills verify --json)
python3 -c '
import json, sys
data = json.loads(sys.argv[1])
assert data["status"] == "passed"
assert data["total_discovered_skills"] == 30
assert len(data["errors"]) == 0
assert len(data["all_skills_merkle_root"]) == 64
' "$VERIFY_JSON"
echo "[PASS] Step 2: Skill bundle verification passed"

echo "==> Step 3: Dry-run compilation across all agents (--agent all --dry-run --json)"
DRY_RUN_JSON=$($PA_BIN skills compile --agent all --dry-run --json)
python3 -c '
import json, sys
data = json.loads(sys.argv[1])
assert len(data) >= 4, "Expected at least 4 compiled agent targets"
for entry in data:
    assert entry["dry_run"] is True
    assert len(entry["merkle_root"]) == 64
    assert len(entry["files"]) > 0
' "$DRY_RUN_JSON"
echo "[PASS] Step 3: Dry-run compilation across all targets passed"

echo "==> Step 4: Staged compilation for Pi agent with role 'traceability_auditor'"
PI_STAGE="$STAGING_DIR/pi"
$PA_BIN skills compile --agent pi --role traceability_auditor --out "$PI_STAGE"

test -f "$PI_STAGE/.pi/skills/traceability-driven-dev/SKILL.md"
test -f "$PI_STAGE/.pi/mcp.json"

# Check frontmatter and body
grep -q "name: traceability-driven-dev" "$PI_STAGE/.pi/skills/traceability-driven-dev/SKILL.md"
grep -q "OpenFastTrace" "$PI_STAGE/.pi/skills/traceability-driven-dev/SKILL.md"

# Check MCP config
python3 -c '
import json, sys
with open(sys.argv[1]) as f:
    cfg = json.load(f)
assert "mcpServers" in cfg
assert "telemetry_acp" in cfg["mcpServers"]
' "$PI_STAGE/.pi/mcp.json"
echo "[PASS] Step 4: Pi skills staged and validated"

echo "==> Step 5: Staged compilation for Claude agent with role 'design_engineer'"
CLAUDE_STAGE="$STAGING_DIR/claude"
$PA_BIN skills compile --agent claude --role design_engineer --out "$CLAUDE_STAGE"

test -f "$CLAUDE_STAGE/CLAUDE.md"
test -f "$CLAUDE_STAGE/.claude/rules/design-system-dev.md"
test -f "$CLAUDE_STAGE/.claude.json"

grep -q "Claude Code Guidelines (Role: design_engineer)" "$CLAUDE_STAGE/CLAUDE.md"
grep -q "design-system-dev" "$CLAUDE_STAGE/.claude/rules/design-system-dev.md"
python3 -c '
import json, sys
with open(sys.argv[1]) as f:
    cfg = json.load(f)
assert "mcpServers" in cfg
assert "design_system_acp" in cfg["mcpServers"]
' "$CLAUDE_STAGE/.claude.json"
echo "[PASS] Step 5: Claude skills staged and validated"

echo "==> Step 6: Staged compilation for Antigravity agent with role 'spec_architect'"
AGY_STAGE="$STAGING_DIR/antigravity"
$PA_BIN skills compile --agent antigravity --role spec_architect --out "$AGY_STAGE"

test -f "$AGY_STAGE/.gemini/skills/traceability-driven-dev/SKILL.md"
test -f "$AGY_STAGE/.gemini/skills/design-system-dev/SKILL.md"
test -f "$AGY_STAGE/.gemini/antigravity/mcp_config.json"
python3 -c '
import json, sys
with open(sys.argv[1]) as f:
    cfg = json.load(f)
assert "mcpServers" in cfg
assert "telemetry_acp" in cfg["mcpServers"]
assert "design_system_acp" in cfg["mcpServers"]
' "$AGY_STAGE/.gemini/antigravity/mcp_config.json"
echo "[PASS] Step 6: Antigravity skills staged and validated"

echo "==> Step 7: Staged compilation for OpenCode agent"
OPENCODE_STAGE="$STAGING_DIR/opencode"
$PA_BIN skills compile --agent opencode --out "$OPENCODE_STAGE"

test -f "$OPENCODE_STAGE/.opencode/instructions.md"
test -d "$OPENCODE_STAGE/.config/opencode/skills"
echo "[PASS] Step 7: OpenCode skills staged and validated"

echo "==> Step 8: Determinism verification across repeated compiles"
STAGE_RUN1="$STAGING_DIR/det1"
STAGE_RUN2="$STAGING_DIR/det2"
$PA_BIN skills compile --agent pi --role traceability_auditor --out "$STAGE_RUN1"
$PA_BIN skills compile --agent pi --role traceability_auditor --out "$STAGE_RUN2"

diff -r "$STAGE_RUN1" "$STAGE_RUN2"
echo "[PASS] Step 8: Bit-for-bit determinism verified"

echo "=========================================================="
echo " ALL E2E SKILL COMPILER TESTS PASSED SUCCESSFULLY!       "
echo "=========================================================="
