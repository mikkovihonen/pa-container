---
name: git
description: Distributed version control system and Git Model Context Protocol (MCP) server.
---

# Git & Git MCP Server

## Overview
Git provides high-performance source control management along with the `mcp-server-git` server for agentic interaction.

## Common Workflows

### 1. Command-Line Git
```bash
git status
git log -n 5 --oneline
git diff
```

### 2. Git MCP Server
The `git` package exposes the `mcp-server-git` binary, providing Model Context Protocol tool endpoints for structured repository exploration and manipulation:
- `git_status`: Inspect working directory state.
- `git_diff`: Show staged or unstaged diffs.
- `git_commit`: Create commits with structured messages.
- `git_log`: Query commit histories.
