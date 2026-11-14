## Reverse Engineering MCP Server

When the `mcp` feature is enabled, the agent has direct access to structured reverse-engineering tools:

- `re_triage`: Returns architecture, format, entry point, sections, and security mitigations as structured JSON.
- `re_disassemble`: Disassembles a range of instructions using Capstone.
- `re_strings`: Searches for strings matching a regex pattern with pagination.
- `re_decompile`: Decompiles a function using Ghidra headless.
- `re_emulate`: Emulates a machine code snippet using Unicorn and returns register outputs.
