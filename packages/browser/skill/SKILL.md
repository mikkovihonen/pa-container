# Browser Automation & MCP (`browser`)

Provides web browser automation, page rendering, DOM inspection, and structured MCP-based browser control using Chrome for Testing and `@playwright/mcp`.

## Constituent Tools
- `chromium`: Chrome for Testing browser engine (also symlinked as `google-chrome`).
- `playwright-mcp`: Official Playwright Model Context Protocol server exposing browser tools over stdio.

## Usage Guidelines
- **CLI Workflows**:
    - Dump DOM in headless mode: `chromium --headless --dump-dom https://example.com`
    - Capture full page screenshot: `chromium --headless --screenshot=/tmp/page.png --window-size=1280,800 https://example.com`
    - Launch interactive browser on virtual desktop: `agent-desktop launch chromium https://example.com`
- **MCP Integration (`@playwright/mcp`)**:
    - Start stdio server: `playwright-mcp`
    - Supports automated navigation, snapshot taking, clicking, typing, and selector evaluation over MCP protocol.
