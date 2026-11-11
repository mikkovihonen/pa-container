---
name: agents
description: Unified coding agent runtimes (Pi, OpenCode, Claude Code, Google Antigravity).
---

# Coding Agents Integration

## Overview

The `agents` capability package provides the execution environments, configuration synthesis, and workspace mounts for AI coding agents.

Available agent engines:
- **Pi**: Fast, lightweight TypeScript coding agent.
- **OpenCode**: Modular agent with full tool and provider interoperability.
- **Claude Code**: Terminal-first agent from Anthropic.
- **Antigravity**: Agent runtime from Google DeepMind with T3 IDE integration.

### Pi Coding Agent (`pi`)

The native Pi coding agent (`@earendil-works/pi-coding-agent`).

#### Common Usage

```bash
pi
pi "Write unit tests for the auth module"
```

### OpenCode Agent (`opencode`)

The OpenCode AI developer assistant CLI.

#### Common Usage

```bash
opencode
opencode "Refactor database connection pooling"
```

### Anthropic Claude Code (`claude`)

The official Anthropic Claude Code CLI.

#### Common Usage

```bash
claude
claude -p "Fix failing integration tests"
```

### Google Antigravity (`agy`)

The Google Antigravity agent CLI and ACP server runtime.

#### Common Usage

```bash
agy
agy "Analyze repository architecture"
```
