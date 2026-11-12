# Language Servers (`language-servers`)

Provides unified Language Server Protocol (LSP) capabilities for code navigation, definitions, references, hover, and refactoring.

## Core Component: `lsp-bridge`
- `lsp-bridge`: Lightweight CLI bridge and MCP adapter for communicating with background Language Server Protocol daemons.
- Verify availability: `lsp-bridge --version`

## General Usage
- Language servers run in the background and respond to JSON-RPC LSP protocol requests.
- Agents interact with language servers either directly via the CLI binary or through MCP navigation tools.
