---
name: zellij
description: Multiplayer terminal workspace with independent multi-user cursors, layouts, and web server.
---

# Zellij Multiplayer Terminal Workspace

Zellij is a terminal multiplexer and workspace with built-in multiplayer collaboration.

## Capabilities

- Multiplayer sessions:
    - Multiple human operators and agents can attach to the same session simultaneously.
    - Each user gets their own cursor, pane focus, and independent navigation.
- Web interface (`zellij web`):
    - Built-in authenticated HTTP/WebSocket server for accessing terminal panes via browser.
- Floating and tiled panes:
    - Highly flexible layout management for monitoring multiple parallel agent runs.

## Common Commands

```sh
# Start a new named session
zellij --session dev-team

# Attach to an existing session
zellij attach dev-team

# List active sessions
zellij list-sessions
```
