# Plan: Agent Orchestrators Capability Package (`agent-orchestrators`)

Status: **Proposed — not yet implemented.** This document specifies the `agent-orchestrators`
Agent Capability Package (ACP) under `pa_packages/agent-orchestrators/`, consolidating the
existing standalone `t3` package into a feature alongside `worktrunk`, `zellij`, and
`agentintercom`. It also defines the native extension, lifecycle hook, and MCP adapter
architecture that gives stock **Pi**, **OpenCode**, **Claude Code**, and **Antigravity**
automatic multi-user and inter-agent messaging over `agentintercom` without requiring custom
agent forks (such as `october-harness`).

## 1. Summary

Replace `pa_packages/t3/` with `pa_packages/agent-orchestrators/`:

| Component | Role | Payload Type | Description |
|---|---|---|---|
| `agent-orchestrators` | Core | `distro_package` (`tmux`, `git`, `jq`) | Detached session execution, `tmux wait-for` synchronization, native `git worktree`, and JSON state parsing |
| `worktrunk` | Feature (`default: true`) | `binary_download` (`wt`) | Branch-addressed Git worktree lifecycle, `.worktreeinclude` state syncing, and copy-on-write build cache sharing |
| `zellij` | Feature (`default: false`) | `binary_download` (`zellij`) | Multiplayer terminal workspace and built-in authenticated web server (`zellij web`) with independent multi-user cursors |
| `t3` | Feature (`default: false`) | `build` (`features/t3/build.sh`, requires `node`) | T3 Code web/desktop control plane and Orchestrator V2 (migrated from `pa_packages/t3/`) |
| `agentintercom` | Feature (`default: false`) | `build` (`features/agentintercom/build.sh`) | Durable local message bus (`agentintercom`) + native extensions, hooks, and STDIO MCP server for **Pi**, **OpenCode**, **Claude Code**, and **Antigravity** |

## 2. Design Principles

1. **One orchestration package, modular features.** Worktree isolation (`worktrunk`),
   multiplayer terminal sharing (`zellij`), web control plane (`t3`), and structured
   inter-agent messaging (`agentintercom`) solve distinct layers of the multi-agent problem.
   Grouping them under `agent-orchestrators` retires the single-tool `t3` package and keeps
   the top-level package catalog clean.
2. **Stock upstream agents, zero forks.** `october-harness` forks Pi solely to poll
   `agentintercom` between turns. Instead of maintaining an unofficial fork, the
   `agentintercom` feature ships lightweight native integrations for all four target
   harnesses (**Pi**, **OpenCode**, **Claude Code**, and **Antigravity**) using their
   official extension, plugin, lifecycle hook, and MCP interfaces.
3. **Hybrid Push + Pull messaging.** Agents need two capabilities to collaborate:
    - **Pull / Action (Tools):** Every agent gets four explicit tools (`intercom_peers`,
      `intercom_send`, `intercom_inbox`, `intercom_ack`) to discover peers, send messages,
      and acknowledge completed requests.
    - **Push / Wakeup (Lifecycle Hooks):** Lifecycle hooks check the unread inbox at turn
      boundaries (`turn_end` / `Stop` / `session.idle` / `PostToolUse`). When a human
      operator or sibling agent sends a message, the hook injects it directly into the
      agent's next turn so the agent reacts automatically.
4. **Shared container-wide message bus directory.** All agents and human operators inside
   the container share `/tmp/pa-intercom` (overridable via `PA_INTERCOM_DIR`, or placed on
   a shared workspace volume when bridging sibling containers). Peer identities default to
   `<harness>-<branch>` (e.g. `pi-feat-auth`, `claude-main`, `human-ops`) and can be
   overridden via `PA_INTERCOM_PEER`.
5. **Non-destructive runtime wiring.** Because `.pa-container` workspaces frequently bind-mount
   host configuration directories (`~/.claude`, `~/.pi`, `~/.config/opencode`, `~/.gemini`),
   build-time files in `/etc/skel` are not enough. `agentintercom` stages its extensions in
   `/usr/local/share/pa-agentintercom/` and ships an idempotent activation script
   (`/usr/local/bin/pa-intercom-activate`, sourced by `/etc/profile.d/pa-agentintercom.sh`)
   that merges hooks/MCP entries via `jq` and symlinks plugins without clobbering user settings.

## 3. Component Inventory

| Component | Version | Ships | License | Installed Size |
|---|---|---|---|---|
| `tmux`, `git`, `jq` (core) | F45 distro | `tmux`, `git`, `jq` | ISC / GPL-2.0 / MIT | ≈ 35 MB (mostly pre-installed) |
| `worktrunk` (`wt`) | 0.81.0 | `/usr/local/bin/wt` (static musl) | MIT OR Apache-2.0 | ≈ 6 MB |
| `zellij` | 0.44.0 | `/usr/local/bin/zellij` (static musl) | MIT | ≈ 32 MB |
| `t3` | pinned | `/usr/local/bin/t3` (+ Node payload) | MIT | ≈ 45 MB (+ `node` ACP) |
| `agentintercom` | pinned | `/usr/local/bin/agentintercom`, `pa-intercom-hook`, `pa-intercom-mcp`, `pa-intercom-activate`, agent extensions | Apache-2.0 | ≈ 8 MB |

## 4. `agentintercom` Extension Specification for Supported Agents

### 4.1 Shared Runtime Primitives

The `agentintercom` feature installs three shared executables and a common environment file
(`/etc/profile.d/pa-agentintercom.sh`):

1. **`/usr/local/bin/agentintercom`**: The Go binary compiled from `october-dev/agentintercom`
    during the builder stage.
2. **`/usr/local/bin/pa-intercom-hook`**: A fast dispatcher invoked by agent lifecycle hooks
   (`SessionStart`, `PostToolUse`, `Stop`, `AfterTool`, `AfterAgent`). It supports four
   subcommands:
    - `pa-intercom-hook register --harness <name>`: Computes deterministic peer ID
      (`${PA_INTERCOM_PEER:-<harness>-<git-branch>}`) and registers the current working
      directory / worktree on the bus.
    - `pa-intercom-hook check-context --harness <name>`: Checks `agentintercom inbox --unread --json`.
      If unread messages exist, formats them and emits harness-specific JSON (`additionalContext`
      for Claude/Antigravity) so the agent sees incoming messages mid-run.
    - `pa-intercom-hook check-stop --harness <name>`: Runs when an agent is about to go idle.
      If unread messages are waiting in the inbox, returns `{"decision": "block", "reason": "..."}`
      so the agent stays awake and processes the incoming message immediately.
    - `pa-intercom-hook drain-text`: Outputs unread messages as plain Markdown and marks them
      delivered, used by Pi and OpenCode in-process extensions.
3. **`/usr/local/bin/pa-intercom-mcp`**: A zero-dependency Python 3 STDIO MCP server
   implementing JSON-RPC 2.0 (`2024-11-05`). It exposes four MCP tools to any MCP-capable
   agent (Antigravity, Claude Code, OpenCode):
    - `intercom_peers`: List active human and agent peers across worktrees (`agentintercom peers --json`).
    - `intercom_send`: Send a message or task to a target peer (`to`, `message`, `topic`, `reply_to`).
    - `intercom_inbox`: Fetch unread or all messages (`unread_only: bool`).
    - `intercom_ack`: Acknowledge a processed message (`message_id`).

---

### 4.2 Pi Coding Agent (`pi`) Extension Specification

- **Target path:** `/usr/local/share/pa-agentintercom/pi/agentintercom.ts`
- **Runtime projection:** Symlinked to `~/.pi/agent/extensions/agentintercom.ts` (and
   optionally `.pi/extensions/agentintercom.ts`).
- **Mechanism:** Uses Pi's native TypeScript Extension API (`ExtensionAPI`):
    1. **Lifecycle hooks:**
        - `pi.on("session_start", ...)`: Registers the Pi session on `agentintercom` as
          `pi-<branch>`.
        - `pi.on("turn_end", ...)` / `pi.on("agent_end", ...)`: Executes
          `pa-intercom-hook drain-text`. When a message from another user or agent arrives while
          Pi is working or just finishing, the extension invokes `pi.sendMessage(...)` with
          `deliverAs: "followUp"` (or `steer`), waking Pi up to handle the message automatically
          just like `october-harness`.
    2. **Registered native tools (`pi.registerTool`):**
        - `intercom_peers`, `intercom_send`, `intercom_inbox`, `intercom_ack`.

---

### 4.3 OpenCode (`opencode`) Plugin Specification

- **Target path:** `/usr/local/share/pa-agentintercom/opencode/agentintercom.mjs`
- **Runtime projection:** Symlinked to `~/.config/opencode/plugin/agentintercom.mjs` AND
  registered under `mcp.agentintercom` in `~/.config/opencode/opencode.json`.
- **Mechanism:** Uses OpenCode's plugin hooks and MCP tool registration:
    1. **Event hooks (`event` handler in plugin):**
        - On `session.created`: Runs `pa-intercom-hook register --harness opencode`.
        - On `tool.execute.after`: Polls `pa-intercom-hook drain-text` and appends any urgent
          incoming peer message to the tool output metadata so OpenCode sees it on the next
          step.
        - On `session.idle`: Checks for unread messages and injects a client prompt turn via
          `client.session.prompt(...)` if a new delegated message arrived.
    2. **Tool integration:** Exposed both via OpenCode plugin `tool` definitions and via
       `pa-intercom-mcp` in `opencode.json`.

---

### 4.4 Claude Code (`claude`) Hook & MCP Specification

- **Target path:** `/usr/local/share/pa-agentintercom/claude/settings-fragment.json`
- **Runtime projection:** Non-destructively merged into `~/.claude/settings.json` and
  `~/.claude.json` (`mcpServers.agentintercom`) by `pa-intercom-activate`.
- **Mechanism:** Combines Claude Code's native lifecycle hooks with the `pa-intercom-mcp`
  server:
    1. **`SessionStart` hook:** Runs `pa-intercom-hook register --harness claude` and prints
       active peers so Claude starts with awareness of the container fleet.
    2. **`UserPromptSubmit` & `PostToolUse` hooks:** Runs
       `pa-intercom-hook check-context --harness claude`. If a colleague or sibling agent sent
       a message, outputs:
       ```json
       {
         "hookSpecificOutput": {
           "hookEventName": "PostToolUse",
           "additionalContext": "[AgentIntercom] Unread message from worker-api (msg_42): Updated schema..."
         }
       }
       ```
    3. **`Stop` hook:** Runs `pa-intercom-hook check-stop --harness claude`. If unread messages
       are queued when Claude finishes its current thought, returns:
       ```json
       {
         "decision": "block",
         "reason": "[AgentIntercom] You have unread messages in your inbox. Process and ack them before stopping: ..."
       }
       ```
    4. **MCP Server (`mcpServers.agentintercom`):** Gives Claude Code first-class
       `mcp__agentintercom__intercom_send`, `intercom_peers`, `intercom_inbox`, and
       `intercom_ack` tools.

---

### 4.5 Antigravity (`antigravity` / Gemini) MCP & Hook Specification

- **Target path:** `/usr/local/share/pa-agentintercom/antigravity/`
- **Runtime projection:**
    - Merges `mcpServers.agentintercom` (`/usr/local/bin/pa-intercom-mcp`) into
      `~/.gemini/antigravity/mcp_config.json` and `~/.gemini/settings.json`.
    - Merges `AfterTool` and `AfterAgent` hooks into `~/.gemini/settings.json` so CLI/headless
      Antigravity runs receive automatic inbox push notifications between steps.
    - Installs an Antigravity workflow rule (`~/.gemini/antigravity/skills/agentintercom/SKILL.md`
      via `pa_core` skill projection) instructing the agent to register on task start and
      check `intercom_inbox` before finalizing cross-worktree tasks.

---

## 5. Package Manifest (`pa_packages/agent-orchestrators/package.yaml`)

```yaml
schema_version: "0.7.0"
name: "agent-orchestrators"
version: "1.0.0"
description: "Multi-agent orchestration capability: tmux session control, parallel Git worktree lifecycle (Worktrunk), multiplayer terminal/web workspace (Zellij), multi-provider web control plane (T3 Code), and inter-agent message bus (AgentIntercom)"
category: "devtools"
license: "MIT AND Apache-2.0"

payload:
    type: distro_package
    packages:
        - "tmux"
        - "git"
        - "jq"

skill:
    enabled: true
    source: "skill/base.md"
    target_agents: ["all"]

features:
    worktrunk:
        description: "Worktrunk (wt) CLI for branch-addressed Git worktree management, .worktreeinclude syncing, copy-on-write build caches, and parallel agent workflows"
        default: true
        payload:
            type: binary_download
            platforms:
                x86_64:
                    url: "[https://github.com/max-sixty/worktrunk/releases/download/v0.81.0/worktrunk-x86_64-unknown-linux-musl.tar.xz](https://github.com/max-sixty/worktrunk/releases/download/v0.81.0/worktrunk-x86_64-unknown-linux-musl.tar.xz)"
                    sha256: "<PIN_X86_64_SHA256_AT_IMPLEMENTATION>"
                    extract_map:
                        "worktrunk-x86_64-unknown-linux-musl/wt": "/usr/local/bin/wt"
                aarch64:
                    url: "[https://github.com/max-sixty/worktrunk/releases/download/v0.81.0/worktrunk-aarch64-unknown-linux-musl.tar.xz](https://github.com/max-sixty/worktrunk/releases/download/v0.81.0/worktrunk-aarch64-unknown-linux-musl.tar.xz)"
                    sha256: "7a334d2e64c577afd0247e2411eff673360ab1f18897564f2d2e5d5374fbd74b"
                    extract_map:
                        "worktrunk-aarch64-unknown-linux-musl/wt": "/usr/local/bin/wt"
        skill_fragment: "features/worktrunk/skill/SKILL.md"
        verification:
            command: "wt --version"
            expected_output_contains: "wt"
    zellij:
        description: "Zellij multiplayer terminal workspace and built-in authenticated web server ('zellij web') with independent multi-user cursors and session tokens"
        default: false
        payload:
            type: binary_download
            platforms:
                x86_64:
                    url: "[https://github.com/zellij-org/zellij/releases/download/v0.44.0/zellij-x86_64-unknown-linux-musl.tar.gz](https://github.com/zellij-org/zellij/releases/download/v0.44.0/zellij-x86_64-unknown-linux-musl.tar.gz)"
                    sha256: "<PIN_X86_64_SHA256_AT_IMPLEMENTATION>"
                    extract_map:
                        "zellij": "/usr/local/bin/zellij"
                aarch64:
                    url: "[https://github.com/zellij-org/zellij/releases/download/v0.44.0/zellij-aarch64-unknown-linux-musl.tar.gz](https://github.com/zellij-org/zellij/releases/download/v0.44.0/zellij-aarch64-unknown-linux-musl.tar.gz)"
                    sha256: "<PIN_AARCH64_SHA256_AT_IMPLEMENTATION>"
                    extract_map:
                        "zellij": "/usr/local/bin/zellij"
        skill_fragment: "features/zellij/skill/SKILL.md"
        verification:
            command: "zellij --version"
            expected_output_contains: "zellij"
    t3:
        description: "T3 Code control surface and Orchestrator V2 for multi-provider agent threads, isolated worktrees, delegated code reviews, and web/desktop access"
        default: false
        runtime:
            dependencies:
                - "node"
        payload:
            type: build
            script: "features/t3/build.sh"
            packages: []
        skill_fragment: "features/t3/skill/SKILL.md"
        verification:
            command: "t3 --version"
            expected_output_contains: "t3"
    agentintercom:
        description: "AgentIntercom message bus and native extensions/hooks/MCP adapters for Pi, OpenCode, Claude Code, and Antigravity enabling real-time multi-user and inter-agent collaboration"
        default: false
        payload:
            type: build
            script: "features/agentintercom/build.sh"
            packages:
                - "python3"
                - "jq"
        skill_fragment: "features/agentintercom/skill/SKILL.md"
        verification:
            command: "agentintercom --help && pa-intercom-hook --version && pa-intercom-mcp --version && test -f /usr/local/share/pa-agentintercom/pi/agentintercom.ts"
            expected_output_contains: "agentintercom"

verification:
    command: "tmux -V && git --version && jq --version"
    expected_output_contains: "tmux"
```

## 6. File Tree

```text
pa_packages/agent-orchestrators/
    package.yaml
    skill/
        base.md
    features/
        worktrunk/
            skill/
                SKILL.md
        zellij/
            skill/
                SKILL.md
        t3/
            build.sh                     # Moved from pa_packages/t3/build.sh
            skill/
                SKILL.md                 # Adapted from pa_packages/t3/SKILL.md
        agentintercom/
            build.sh
            bin/
                pa-intercom-hook
                pa-intercom-mcp
                pa-intercom-activate
            extensions/
                pi/
                    agentintercom.ts
                opencode/
                    agentintercom.mjs
                claude/
                    settings-fragment.json
                antigravity/
                    mcp-fragment.json
            skill/
                SKILL.md
```

---

## 7. Implementation Artifacts (`agentintercom` Feature)

### 7.1 `pa_packages/agent-orchestrators/features/agentintercom/build.sh`

```sh
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_ROOT="${STAGE_DIR:-}"

INTERCOM_REPO="[https://github.com/october-dev/agentintercom.git](https://github.com/october-dev/agentintercom.git)"
INTERCOM_COMMIT="<PIN_COMMIT_SHA_AT_IMPLEMENTATION>"

microdnf install -y golang git ca-certificates

BUILD_TMP="$(mktemp -d)"
trap 'rm -rf "${BUILD_TMP}"' EXIT

git clone "${INTERCOM_REPO}" "${BUILD_TMP}/agentintercom"
git -C "${BUILD_TMP}/agentintercom" checkout "${INTERCOM_COMMIT}"

mkdir -p \
    "${TARGET_ROOT}/usr/local/bin" \
    "${TARGET_ROOT}/usr/local/share/pa-agentintercom" \
    "${TARGET_ROOT}/etc/profile.d"

(
    cd "${BUILD_TMP}/agentintercom"
    CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" \
        -o "${TARGET_ROOT}/usr/local/bin/agentintercom" .
)

install -m 0755 "${SCRIPT_DIR}/bin/pa-intercom-hook" "${TARGET_ROOT}/usr/local/bin/pa-intercom-hook"
install -m 0755 "${SCRIPT_DIR}/bin/pa-intercom-mcp" "${TARGET_ROOT}/usr/local/bin/pa-intercom-mcp"
install -m 0755 "${SCRIPT_DIR}/bin/pa-intercom-activate" "${TARGET_ROOT}/usr/local/bin/pa-intercom-activate"

cp -R "${SCRIPT_DIR}/extensions/"* "${TARGET_ROOT}/usr/local/share/pa-agentintercom/"

cat > "${TARGET_ROOT}/etc/profile.d/pa-agentintercom.sh" <<'EOF'
export PA_INTERCOM_DIR="${PA_INTERCOM_DIR:-/tmp/pa-intercom}"
if command -v pa-intercom-activate >/dev/null 2>&1; then
    pa-intercom-activate --quiet || true
fi
EOF
chmod 0644 "${TARGET_ROOT}/etc/profile.d/pa-agentintercom.sh"
```

---

### 7.2 `pa_packages/agent-orchestrators/features/agentintercom/bin/pa-intercom-hook`

Universal hook dispatcher for Claude Code, Antigravity/Gemini CLI, Pi, and OpenCode:

```python
#!/usr/bin/env python3
"""Universal AgentIntercom lifecycle hook dispatcher for pa-container agents."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def git_branch() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
        ).strip()
        return out.replace("/", "-") if out else "workspace"
    except Exception:
        return Path.cwd().name or "workspace"


def peer_name(harness: str) -> str:
    env_peer = os.environ.get("PA_INTERCOM_PEER", "").strip()
    if env_peer:
        return env_peer
    return f"{harness}-{git_branch()}"


def run_intercom(args: list[str], peer: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.setdefault("PA_INTERCOM_DIR", "/tmp/pa-intercom")
    env["AGENTINTERCOM_PEER"] = peer
    return subprocess.run(
        ["agentintercom", *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )


def fetch_unread(peer: str) -> list[dict]:
    res = run_intercom(["inbox", "--unread", "--json"], peer)
    if res.returncode != 0 or not res.stdout.strip():
        return []
    try:
        data = json.loads(res.stdout)
        return data if isinstance(data, list) else data.get("messages", [])
    except Exception:
        return []


def format_messages(messages: list[dict]) -> str:
    lines = ["[AgentIntercom] Incoming unread messages:"]
    for m in messages:
        msg_id = m.get("id", "unknown")
        sender = m.get("from", "peer")
        body = m.get("message") or m.get("body") or ""
        lines.append(f"- (id={msg_id}) from {sender}: {body}")
    lines.append("Reply with `intercom_send` and mark handled with `intercom_ack`.")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(prog="pa-intercom-hook")
    parser.add_argument("--version", action="version", version="pa-intercom-hook 1.0.0")
    sub = parser.add_subparsers(dest="cmd")

    for name in ("register", "check-context", "check-stop", "drain-text"):
        p = sub.add_parser(name)
        p.add_argument("--harness", default="agent")
        p.add_argument("--ack", action="store_true")

    args = parser.parse_args()
    if not args.cmd:
        parser.print_help()
        return 0

    peer = peer_name(args.harness)

    if args.cmd == "register":
        run_intercom(["register", "--name", peer, "--worktree", str(Path.cwd())], peer)
        return 0

    messages = fetch_unread(peer)
    if not messages:
        return 0

    summary = format_messages(messages)

    if args.ack:
        for m in messages:
            if m.get("id"):
                run_intercom(["ack", str(m["id"])], peer)

    if args.cmd == "drain-text":
        print(summary)
        return 0

    if args.cmd == "check-context":
        payload = {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": summary,
            }
        }
        print(json.dumps(payload))
        return 0

    if args.cmd == "check-stop":
        payload = {
            "decision": "block",
            "reason": summary,
        }
        print(json.dumps(payload))
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
```

---

### 7.3 `pa_packages/agent-orchestrators/features/agentintercom/bin/pa-intercom-mcp`

Zero-dependency STDIO MCP server for Antigravity, Claude Code, and OpenCode:

```python
#!/usr/bin/env python3
"""STDIO Model Context Protocol (MCP) server for AgentIntercom."""

import json
import os
import subprocess
import sys
from pathlib import Path

SERVER_INFO = {"name": "pa-agentintercom", "version": "1.0.0"}

TOOLS = [
    {
        "name": "intercom_peers",
        "description": "List active human and coding agent peers registered on AgentIntercom across worktrees.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "intercom_send",
        "description": "Send a structured message, API contract update, or delegated task to another peer on AgentIntercom.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient peer name (or 'all' for broadcast)"},
                "message": {"type": "string", "description": "Message body"},
            },
            "required": ["to", "message"],
        },
    },
    {
        "name": "intercom_inbox",
        "description": "Read incoming messages in the current agent's durable AgentIntercom inbox.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "unread_only": {"type": "boolean", "default": True},
            },
        },
    },
    {
        "name": "intercom_ack",
        "description": "Acknowledge a message ID in the AgentIntercom inbox after acting on it.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "message_id": {"type": "string", "description": "Message ID to acknowledge"},
            },
            "required": ["message_id"],
        },
    },
]


def call_cli(cli_args: list[str]) -> str:
    env = os.environ.copy()
    env.setdefault("PA_INTERCOM_DIR", "/tmp/pa-intercom")
    res = subprocess.run(
        ["agentintercom", *cli_args],
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    output = (res.stdout or "") + (res.stderr or "")
    return output.strip() or "OK"


def handle_request(req: dict) -> dict | None:
    method = req.get("method")
    req_id = req.get("id")

    if method == "initialize":
        subprocess.run(
            ["pa-intercom-hook", "register", "--harness", "mcp"],
            capture_output=True,
            check=False,
        )
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": SERVER_INFO,
            },
        }

    if method == "notifications/initialized":
        return None

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}}

    if method == "tools/call":
        params = req.get("params", {})
        name = params.get("name")
        args = params.get("arguments", {}) or {}

        if name == "intercom_peers":
            text = call_cli(["peers", "--json"])
        elif name == "intercom_send":
            text = call_cli(["send", "--to", str(args.get("to", "")), "--message", str(args.get("message", ""))])
        elif name == "intercom_inbox":
            flags = ["inbox", "--json"]
            if args.get("unread_only", True):
                flags.insert(1, "--unread")
            text = call_cli(flags)
        elif name == "intercom_ack":
            text = call_cli(["ack", str(args.get("message_id", ""))])
        else:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Unknown tool: {name}"},
            }

        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"content": [{"type": "text", "text": text}]},
        }

    if req_id is not None:
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}
    return None


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--version":
        print("pa-intercom-mcp 1.0.0")
        return 0

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            resp = handle_request(req)
            if resp is not None:
                sys.stdout.write(json.dumps(resp) + "\n")
                sys.stdout.flush()
        except Exception as exc:
            sys.stderr.write(f"pa-intercom-mcp error: {exc}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

---

### 7.4 Pi Extension (`extensions/pi/agentintercom.ts`)

Gives official **Pi Coding Agent** (`pi`) automatic between-turn inbox delivery and native
`intercom_*` tools without needing the `october-harness` fork:

```typescript
// pa-container AgentIntercom extension for official Pi Coding Agent
import { execFileSync } from "node:child_process";

export default function agentIntercomExtension(pi: any) {
    const runCli = (args: string[]): string => {
        try {
            return execFileSync("agentintercom", args, {
                encoding: "utf-8",
                timeout: 5000,
            }).trim();
        } catch (err: any) {
            return err?.stdout?.toString() || err?.message || "agentintercom error";
        }
    };

    const drainUnread = (): string => {
        try {
            return execFileSync(
                "pa-intercom-hook",
                ["drain-text", "--harness", "pi", "--ack"],
                { encoding: "utf-8", timeout: 5000 }
            ).trim();
        } catch {
            return "";
        }
    };

    pi.on("session_start", async () => {
        try {
            execFileSync("pa-intercom-hook", ["register", "--harness", "pi"], {
                timeout: 3000,
            });
        } catch {
            // Ignore registration errors if bus is not yet initialized
        }
    });

    // Poll unread inbox after every turn; if a human or peer agent sent a message,
    // inject it as a followUp message so Pi processes it automatically.
    pi.on("turn_end", async () => {
        const incoming = drainUnread();
        if (incoming && typeof pi.sendMessage === "function") {
            pi.sendMessage(
                {
                    customType: "agentintercom-inbox",
                    content: incoming,
                    display: true,
                },
                { deliverAs: "followUp", triggerTurn: true }
            );
        }
    });

    pi.registerTool({
        name: "intercom_peers",
        label: "Intercom Peers",
        description: "List active human and agent peers registered on AgentIntercom",
        parameters: { type: "object", properties: {} },
        async execute() {
            return { content: [{ type: "text", text: runCli(["peers", "--json"]) }] };
        },
    });

    pi.registerTool({
        name: "intercom_send",
        label: "Intercom Send",
        description: "Send a message or task to another peer on AgentIntercom",
        parameters: {
            type: "object",
            properties: {
                to: { type: "string", description: "Target peer name" },
                message: { type: "string", description: "Message content" },
            },
            required: ["to", "message"],
        },
        async execute(_id: string, params: { to: string; message: string }) {
            const out = runCli(["send", "--to", params.to, "--message", params.message]);
            return { content: [{ type: "text", text: out || "Sent" }] };
        },
    });

    pi.registerTool({
        name: "intercom_inbox",
        label: "Intercom Inbox",
        description: "Check unread messages in the AgentIntercom inbox",
        parameters: { type: "object", properties: {} },
        async execute() {
            return { content: [{ type: "text", text: runCli(["inbox", "--unread", "--json"]) }] };
        },
    });

    pi.registerTool({
        name: "intercom_ack",
        label: "Intercom Ack",
        description: "Acknowledge a processed AgentIntercom message ID",
        parameters: {
            type: "object",
            properties: {
                message_id: { type: "string", description: "Message ID to acknowledge" },
            },
            required: ["message_id"],
        },
        async execute(_id: string, params: { message_id: string }) {
            return { content: [{ type: "text", text: runCli(["ack", params.message_id]) }] };
        },
    });
}
```

---

### 7.5 OpenCode Plugin (`extensions/opencode/agentintercom.mjs`)

```javascript
// pa-container AgentIntercom plugin for OpenCode
import { execFileSync } from "node:child_process";

export const AgentIntercomPlugin = async ({ client }) => {
    const drainUnread = () => {
        try {
            return execFileSync(
                "pa-intercom-hook",
                ["drain-text", "--harness", "opencode", "--ack"],
                { encoding: "utf-8", timeout: 5000 }
            ).trim();
        } catch {
            return "";
        }
    };

    return {
        event: async ({ event }) => {
            if (event.type === "session.created") {
                try {
                    execFileSync("pa-intercom-hook", ["register", "--harness", "opencode"], {
                        timeout: 3000,
                    });
                } catch {}
            }

            if (event.type === "session.idle") {
                const incoming = drainUnread();
                if (incoming && client?.session?.prompt && event.properties?.sessionID) {
                    await client.session.prompt({
                        path: { id: event.properties.sessionID },
                        body: {
                            parts: [{ type: "text", text: incoming }],
                        },
                    });
                }
            }
        },
    };
};

export default AgentIntercomPlugin;
```

---

### 7.6 Claude Code & Antigravity Activation (`bin/pa-intercom-activate`)

Idempotently wires all four agents on container startup without overwriting user config:

```sh
#!/usr/bin/env bash
set -euo pipefail

SHARE_DIR="/usr/local/share/pa-agentintercom"

# 1. Pi Coding Agent: symlink extension into ~/.pi/agent/extensions/
mkdir -p "${HOME}/.pi/agent/extensions"
ln -sf "${SHARE_DIR}/pi/agentintercom.ts" "${HOME}/.pi/agent/extensions/agentintercom.ts"

# 2. OpenCode: symlink plugin and register MCP server in ~/.config/opencode/opencode.json
mkdir -p "${HOME}/.config/opencode/plugin"
ln -sf "${SHARE_DIR}/opencode/agentintercom.mjs" "${HOME}/.config/opencode/plugin/agentintercom.mjs"
OPENCODE_CFG="${HOME}/.config/opencode/opencode.json"
if [ ! -f "${OPENCODE_CFG}" ]; then
    echo '{}' > "${OPENCODE_CFG}"
fi
jq '.mcp.agentintercom = {"type": "local", "command": ["/usr/local/bin/pa-intercom-mcp"], "enabled": true}' \
    "${OPENCODE_CFG}" > "${OPENCODE_CFG}.tmp" && mv "${OPENCODE_CFG}.tmp" "${OPENCODE_CFG}"

# 3. Claude Code: merge lifecycle hooks into ~/.claude/settings.json and MCP into ~/.claude.json
mkdir -p "${HOME}/.claude"
CLAUDE_SETTINGS="${HOME}/.claude/settings.json"
if [ ! -f "${CLAUDE_SETTINGS}" ]; then
    echo '{}' > "${CLAUDE_SETTINGS}"
fi
jq -s '.[0] * .[1]' "${CLAUDE_SETTINGS}" "${SHARE_DIR}/claude/settings-fragment.json" \
    > "${CLAUDE_SETTINGS}.tmp" && mv "${CLAUDE_SETTINGS}.tmp" "${CLAUDE_SETTINGS}"

CLAUDE_JSON="${HOME}/.claude.json"
if [ ! -f "${CLAUDE_JSON}" ]; then
    echo '{}' > "${CLAUDE_JSON}"
fi
jq '.mcpServers.agentintercom = {"command": "/usr/local/bin/pa-intercom-mcp", "args": []}' \
    "${CLAUDE_JSON}" > "${CLAUDE_JSON}.tmp" && mv "${CLAUDE_JSON}.tmp" "${CLAUDE_JSON}"

# 4. Antigravity / Gemini: merge MCP server and hooks into ~/.gemini/antigravity/mcp_config.json & ~/.gemini/settings.json
mkdir -p "${HOME}/.gemini/antigravity"
AG_MCP="${HOME}/.gemini/antigravity/mcp_config.json"
if [ ! -f "${AG_MCP}" ]; then
    echo '{}' > "${AG_MCP}"
fi
jq '.mcpServers.agentintercom = {"command": "/usr/local/bin/pa-intercom-mcp", "args": []}' \
    "${AG_MCP}" > "${AG_MCP}.tmp" && mv "${AG_MCP}.tmp" "${AG_MCP}"

GEMINI_SETTINGS="${HOME}/.gemini/settings.json"
if [ ! -f "${GEMINI_SETTINGS}" ]; then
    echo '{}' > "${GEMINI_SETTINGS}"
fi
jq -s '.[0] * .[1]' "${GEMINI_SETTINGS}" "${SHARE_DIR}/antigravity/mcp-fragment.json" \
    > "${GEMINI_SETTINGS}.tmp" && mv "${GEMINI_SETTINGS}.tmp" "${GEMINI_SETTINGS}"
```

#### `extensions/claude/settings-fragment.json`

```json
{
    "hooks": {
        "SessionStart": [
            {
                "matcher": "*",
                "hooks": [
                    {
                        "type": "command",
                        "command": "/usr/local/bin/pa-intercom-hook register --harness claude"
                    }
                ]
            }
        ],
        "PostToolUse": [
            {
                "matcher": "*",
                "hooks": [
                    {
                        "type": "command",
                        "command": "/usr/local/bin/pa-intercom-hook check-context --harness claude --ack"
                    }
                ]
            }
        ],
        "Stop": [
            {
                "matcher": "*",
                "hooks": [
                    {
                        "type": "command",
                        "command": "/usr/local/bin/pa-intercom-hook check-stop --harness claude --ack"
                    }
                ]
            }
        ]
    }
}
```

#### `extensions/antigravity/mcp-fragment.json`

```json
{
    "mcpServers": {
        "agentintercom": {
            "command": "/usr/local/bin/pa-intercom-mcp",
            "args": []
        }
    },
    "hooks": {
        "SessionStart": [
            {
                "matcher": "*",
                "hooks": [
                    {
                        "type": "command",
                        "command": "/usr/local/bin/pa-intercom-hook register --harness antigravity"
                    }
                ]
            }
        ],
        "AfterTool": [
            {
                "matcher": "*",
                "hooks": [
                    {
                        "type": "command",
                        "command": "/usr/local/bin/pa-intercom-hook check-context --harness antigravity --ack"
                    }
                ]
            }
        ]
    }
}
```

---

## 8. Skill Files (`skill/base.md` and Feature `SKILL.md` Fragments)

````markdown
# ==============================================================================
# FILE: pa_packages/agent-orchestrators/features/agentintercom/skill/SKILL.md
# ==============================================================================
## Feature: `agentintercom` (Multi-User & Inter-Agent Message Bus)

`agentintercom` provides a durable local message bus (`PA_INTERCOM_DIR=/tmp/pa-intercom`) for structured communication, task handoffs, and acknowledgments between human operators and parallel coding agents (**Pi**, **OpenCode**, **Claude Code**, and **Antigravity**) running across Git worktrees.

### Native Agent Extensions (Zero-Fork Push & Pull)

When this feature is enabled, `/usr/local/bin/pa-intercom-activate` automatically configures all four supported harnesses:

| Agent Harness | Integration Mechanism | Automatic Push Behavior | Available Native / MCP Tools |
|---|---|---|---|
| **Pi** (`pi`) | `~/.pi/agent/extensions/agentintercom.ts` | Polls inbox on `turn_end` and triggers a `followUp` turn automatically | `intercom_peers`, `intercom_send`, `intercom_inbox`, `intercom_ack` |
| **OpenCode** (`opencode`) | `~/.config/opencode/plugin/agentintercom.mjs` + MCP | Polls inbox on `session.idle` and injects a prompt into the active session | `intercom_peers`, `intercom_send`, `intercom_inbox`, `intercom_ack` |
| **Claude Code** (`claude`) | `~/.claude/settings.json` hooks + MCP | `PostToolUse` injects `additionalContext`; `Stop` blocks idle transition if unread messages exist | `mcp__agentintercom__intercom_*` |
| **Antigravity** (`antigravity`) | `~/.gemini/antigravity/mcp_config.json` + hooks | `AfterTool` injects incoming messages into context | `intercom_peers`, `intercom_send`, `intercom_inbox`, `intercom_ack` |

### CLI Usage (For Human Operators and Shell Scripts)

Human operators attached via `zellij` or `tmux` can message any running agent directly from the shell:

```sh
# 1. Register a human operator identity or override an agent's peer name
export PA_INTERCOM_PEER="human-lead"
agentintercom register --name "$PA_INTERCOM_PEER" --worktree "$(pwd)"

# 2. List all active peers (e.g., pi-feat-api, claude-feat-ui, antigravity-review)
agentintercom peers --json | jq '.'

# 3. Send instructions or review feedback directly into a running agent's inbox
agentintercom send --to "pi-feat-api" \
    --message "Please add rate-limiting headers to POST /v1/tokens before merging."

# 4. Inspect your own unread inbox and acknowledge messages
agentintercom inbox --unread --json
agentintercom ack <message-id>
```

---

## 9. Rollout Steps

1. Create pa_packages/agent-orchestrators/ and move pa_packages/t3/build.sh into
pa_packages/agent-orchestrators/features/t3/build.sh.
2. Remove pa_packages/t3/ and update references in docs/configuration.md,CHANGELOG.md, and tests/.
3. Add worktrunk, zellij, and agentintercom feature directories, scripts, and skills.
4. Run uv run pytest, uv run pre-commit run --all-files, and smoke-test all four
features with pa build --packages agent-orchestrators --features worktrunk,zellij,t3,agentintercom
and pa test --packages agent-orchestrators --features worktrunk,zellij,t3,agentintercom.
