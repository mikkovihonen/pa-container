---
name: t3
description: T3 Code collaborative multi-agent web interface and control surface.
---

# T3 Code Web Interface

T3 Code provides a browser-based and desktop interface for orchestrating multi-provider coding agents across isolated Git worktrees.

## Features

- Multi-provider support:
    - Connects to Pi, Claude Code, OpenCode, and Antigravity.
- Worktree isolation:
    - Runs agent tasks in designated Git worktrees to prevent workspace collisions.
- Remote pairing & tunnels:
    - Pairs securely via local network or automated Cloudflare/Tailscale tunnels.

## Usage

```sh
# Start container in T3 server mode
pa run --t3

# Expose over local network
pa run --t3 --t3-lan

# Expose via Cloudflare tunnel
pa run --t3 --t3-tunnel cloudflare --t3-tunnel-quick
```
