# Headless Browser Runtime Libraries (`chromium-headless`)

Provides the shared system libraries (NSS, NSPR, ATK, AT-SPI, ALSA, X11, GBM, Cairo, Pango, CUPS, D-Bus) that headless Chromium engines require.

## Usage Guidelines
- **Playwright**: `npm install playwright` and `npx playwright install chromium` download a browser build that runs headless out of the box.
- **Puppeteer**: `npm install puppeteer` downloads Chrome for Testing automatically.
- This feature ships no `chromium` binary. Use the `chromium` feature for the preinstalled Chrome for Testing engine and the Playwright MCP server.
