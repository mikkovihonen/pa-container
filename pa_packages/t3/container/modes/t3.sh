#!/bin/bash
set -e

if ! command -v t3 >/dev/null 2>&1; then
    echo "ERROR: t3 CLI is not installed in the container." >&2
    echo "Install it via packages: [\"t3\"], npm install -g t3, or .pa-container/dependencies/root/commands.sh." >&2
    exit 1
fi

# Seed pre-installed T3 managed runtimes into /home/agent/.t3/tools if available
if [ -d "/usr/local/share/t3/tools/antigravity-acp" ]; then
    mkdir -p /home/agent/.t3/tools
    cp -a /usr/local/share/t3/tools/antigravity-acp /home/agent/.t3/tools/ 2>/dev/null || true
fi

# Preflight login check for agent-native authenticated agents in T3 mode
if [[ ",${PA_CONTAINER_ENABLED_AGENTS:-$PA_CONTAINER_AGENT}," == *",claude,"* ]] && [ -z "${ANTHROPIC_API_KEY}" ]; then
    if command -v claude >/dev/null 2>&1; then
        _auth_status=$(CLAUDE_CONFIG_DIR=/home/agent/.claude claude auth status --json 2>/dev/null || true)
        if ! echo "$_auth_status" | grep -q "\"loggedIn\"[[:space:]]*:[[:space:]]*true"; then
            echo "=================================================================="
            echo "  Claude Code requires authentication before starting T3."
            echo "  Starting interactive login..."
            echo "=================================================================="
            CLAUDE_CONFIG_DIR=/home/agent/.claude claude auth login
        fi
    fi
fi

if [[ ",${PA_CONTAINER_ENABLED_AGENTS:-$PA_CONTAINER_AGENT}," == *",antigravity,"* ]] && [ -z "${GEMINI_API_KEY}" ]; then
    if command -v agy >/dev/null 2>&1; then
        if [ ! -f /home/agent/.gemini/antigravity-cli/antigravity-oauth-token ]; then
            echo "=================================================================="
            echo "  Antigravity requires authentication before starting T3."
            echo "  Starting interactive login..."
            echo "=================================================================="
            agy --dangerously-skip-permissions -p "Authentication check" || true
        fi
    fi
fi

# Sync Antigravity OAuth tokens to T3 ACP credentials store
if [ -f /home/agent/.gemini/antigravity-cli/antigravity-oauth-token ]; then
    if [ -f /usr/local/share/pa-container/t3-sync-antigravity.py ]; then
        python3 /usr/local/share/pa-container/t3-sync-antigravity.py 2>/dev/null || true
    fi
fi

echo "=================================================================="
echo "  Starting T3 Code server for ${PA_CONTAINER_AGENT} inside pa-container..."
echo "  Web UI: https://t3.codes"
if [ -n "${T3_PUBLIC_URL}" ]; then
    echo "  Tunnel URL: ${T3_PUBLIC_URL}"
fi
echo "=================================================================="
_shim="/usr/local/share/pa-container/t3-advertise-host.cjs"
if [ -f "$_shim" ]; then
    export NODE_OPTIONS="${NODE_OPTIONS:+${NODE_OPTIONS} }--require ${_shim}"
fi
export T3_ADVERTISE_HOST="${T3_ADVERTISE_HOST}"
extra_args=()
if [ "${T3_LAN}" = "true" ]; then
    extra_args+=("--lan")
fi

exec t3 serve --base-dir /home/agent/.t3 --host 0.0.0.0 --port "${T3_PORT:-3773}" "${extra_args[@]}" "$@"
