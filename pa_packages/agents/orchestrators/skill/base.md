---
name: agent-orchestrators
description: Multi-agent orchestration, session management, parallel Git worktrees, and inter-agent communication.
---

# Agent Orchestrators Capability

The `agent-orchestrators` capability package provides terminal multiplexing, detached session execution, parallel Git worktree workflows, and collaborative inter-agent messaging.

## Components

- **Base terminal tools (`agent-orchestrators/base`)**:
    - `tmux`: Detached session control and pane management.
    - `git`: Native revision control and worktree operations (`git worktree`).
    - `jq`: Command-line JSON processor for scripting and state extraction.
- **Worktree manager (`agent-orchestrators/worktrunk`)**:
    - `wt`: Branch-addressed Git worktree lifecycle and state synchronization via `.worktreeinclude`.
- **Multiplayer terminal (`agent-orchestrators/zellij`)**:
    - `zellij`: Multiplayer terminal workspace with independent cursors and built-in web server (`zellij web`).
- **Web control plane (`agent-orchestrators/t3`)**:
    - `t3`: Collaborative multi-agent web interface and control surface.
- **Inter-agent message bus (`agent-orchestrators/agentintercom`)**:
    - `agentintercom`: Local message bus and native zero-fork extensions for Pi, OpenCode, Claude Code, and Antigravity.
