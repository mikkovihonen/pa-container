---
name: agentintercom
description: Durable local message bus and native zero-fork extensions for cross-worktree agent collaboration.
---

# AgentIntercom Message Bus

`agentintercom` provides a durable local message bus (`PA_INTERCOM_DIR=/tmp/pa-intercom`) for structured communication, task handoffs, and acknowledgments between human operators and parallel coding agents (**Pi**, **OpenCode**, **Claude Code**, and **Antigravity**) running across Git worktrees.

## Native Agent Extensions (Zero-Fork Push & Pull)

When this capability is enabled, `/usr/local/bin/pa-intercom-activate` automatically configures all four supported harnesses:

| Agent Harness | Integration Mechanism | Automatic Push Behavior | Available Native / MCP Tools |
|---|---|---|---|
| **Pi** (`pi`) | `~/.pi/agent/extensions/agentintercom.ts` | Polls inbox on `turn_end` and triggers a `followUp` turn automatically | `intercom_peers`, `intercom_send`, `intercom_inbox`, `intercom_ack` |
| **OpenCode** (`opencode`) | `~/.config/opencode/plugin/agentintercom.mjs` + MCP | Polls inbox on `session.idle` and injects a prompt into the active session | `intercom_peers`, `intercom_send`, `intercom_inbox`, `intercom_ack` |
| **Claude Code** (`claude`) | `~/.claude/settings.json` hooks + MCP | `PostToolUse` injects `additionalContext`; `Stop` blocks idle transition if unread messages exist | `mcp__agentintercom__intercom_*` |
| **Antigravity** (`antigravity`) | `~/.gemini/antigravity/mcp_config.json` + hooks | `AfterTool` injects incoming messages into context | `intercom_peers`, `intercom_send`, `intercom_inbox`, `intercom_ack` |

## CLI Usage (For Human Operators and Shell Scripts)

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
