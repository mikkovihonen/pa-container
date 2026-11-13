---
name: language-servers
description: Optional language servers (clangd, pyright, rust-analyzer, typescript-language-server, zls) with the lsp-bridge status CLI.
---

# Language Servers (`language-servers`)

## Status Bridge (`lsp-bridge`)
- `lsp-bridge`: CLI status bridge for the language server capability.
- Confirm that the capability is active: `lsp-bridge`
- Check the version: `lsp-bridge --version`

## Optional Language Servers
Enable a server as a feature in `.pa-container/config.yaml` under `language-servers`:
- `clangd`: C and C++ language server. Use it for index-based completion, navigation, and static analysis.
- `pyright`: Python type checker and language server.
- `rust-analyzer`: Rust language server. Use it for semantic navigation, inlay hints, and diagnostics.
- `typescript`: TypeScript and JavaScript language server (`typescript-language-server`).
- `zls`: Zig language server. Use it for completion, definitions, and diagnostics.

Language servers speak JSON-RPC over stdio. Run the version command of a server (for example `pyright --version`) to confirm that the server is installed.
