---
name: developer-tools
description: "Core developer CLI utilities: Just task runner, Ripgrep fast search, fd file finder, jq JSON filtering, fzf fuzzy search, curl, and wget."
---

# Developer Tools (`developer-tools`)

Provides foundational CLI tools for developer automation, project task execution, codebase searching, and structured JSON parsing.

## Tool Overview

| Task | Tool | Primary Command |
|---|---|---|
| Project task execution | `just` | `just test`, `just build` |
| Fast codebase regex search | `rg` (`ripgrep`) | `rg "pattern" --type rust` |
| Fast file and directory discovery | `fd` / `fd-find` | `fd "\.toml$"` |
| Structured JSON stream filtering | `jq` | `jq -r '.key' file.json` |
| HTTP/HTTPS web requests and downloads | `curl` / `wget` | `curl -fsSL https://...` |
| Interactive / scripted fuzzy filtering | `fzf` | `find . \| fzf --filter="query"` |

## Common Recipes

### Codebase Search with Ripgrep

```sh
# Search for symbols across code files, ignoring binaries and hidden dirs
rg "fn handle_agent" crates/

# Search with line numbers and file types
rg --type py "class Agent"
```

### File Discovery with fd

```sh
# Find files by extension excluding target directory
fd -e toml -E "target"

# Execute command on each found file
fd -e md -x head -n 5 {}
```

### Automated Task Execution with Just

```sh
# List available project tasks
just --list

# Run specific recipe
just build
just test
```

## Guidelines
- **Binary portability**: Note that on Fedora the `fd` binary is named `fd-find` (with `fd` symlink). On macOS Homebrew it is `fd`.
- **JSON Processing**: Prefer `jq` for extracting nested fields or formatting JSON outputs over raw regex or awk.
