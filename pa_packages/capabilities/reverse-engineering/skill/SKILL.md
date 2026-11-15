---
name: reverse-engineering
description: "Binary triage, decompilation, and firmware reverse engineering using Ghidra headless, Radare2, Capstone, and structured MCP tools."
---

# Reverse Engineering & Firmware Analysis (`reverse-engineering`)

Provides tools for inspecting legacy applications, compiled device firmware, and proprietary binaries to recover software logic, extract data structures, and ensure business continuity.

## Tool Overview

| Task | Tool | Primary Command |
|---|---|---|
| Binary format and architecture triage | `file` / `readelf` | `file firmware.bin`, `readelf -h app.elf` |
| Fast string extraction and filtering | `strings` | `strings -a -n 8 binary \| grep -iE 'http\|key\|pass'` |
| Disassembly and symbol analysis | `radare2` / `r2` | `r2 -A -c "afl" binary` |
| Headless single-function decompilation | `ghidra-decompile` | `ghidra-decompile binary main` |
| Batch Ghidra headless analysis | `analyzeHeadless` | `analyzeHeadless /tmp/proj P -import bin -postScript script.py` |
| Structured JSON-RPC MCP analysis | `reverse-engineering` MCP | Tool calls: `re_triage`, `re_decompile`, `re_strings` |

## Triage & Decompilation Workflow

### 1. File Identification and Section Triage

```sh
# Identify architecture, endianness, and bitness
file target_binary

# Check ELF/PE headers and section layouts
readelf -h target_binary
readelf -S target_binary
```

### 2. Decompilation with Ghidra Headless

Use `ghidra-decompile` to decompile functions directly to clean C source code:

```sh
# List all discovered functions and entry points
ghidra-decompile target_binary

# Decompile a specific function by name or address
ghidra-decompile target_binary main
ghidra-decompile target_binary 0x00401a20
```

### 3. Structured Reverse-Engineering MCP Server

When using MCP-enabled agents (Claude Code, Antigravity, Pi), the `mcp/server.py` server provides native tool calls:
- `re_triage`: Returns file architecture, format, entry points, and section layout as structured JSON.
- `re_strings`: Searches for strings matching regex patterns with pagination.
- `re_disassemble`: Disassembles instruction bytes using Capstone.
- `re_decompile`: Invokes Ghidra headless and returns high-level decompiled C syntax.
- `re_emulate`: Emulates machine code instructions with Unicorn and returns register states.

## Guidelines
- **JVM performance**: Ghidra boots a JVM on each headless invocation (~10-15s startup). Prefer batch analysis or inspecting symbols first before decompiling.
- **Output paths**: Write temporary project files and disassembly dumps to `/tmp/pa-re`.
