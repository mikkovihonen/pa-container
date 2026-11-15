---
name: browser
description: "Web browser automation, page rendering, DOM inspection, full-page screenshots, and Playwright/Puppeteer automation in headless environments."
---

# Browser Automation (`browser`)

Provides browser automation capabilities for testing web applications, inspecting DOM structures, capturing full-page screenshots, and running headless end-to-end integration tests.

## Common CLI Recipes

### Headless DOM Dump and Text Extraction

```sh
# Dump evaluated DOM HTML to stdout
chromium --headless=new --dump-dom https://example.com

# Capture clean screenshot with custom viewport
chromium --headless=new --screenshot=/tmp/page.png --window-size=1280,800 https://example.com
```

### Headless Automation with Playwright

Playwright runs out of the box in headless environments:

```javascript
// example.js
const { chromium } = require('playwright');

(async () => {
    const browser = await chromium.launch({ headless: true });
    const page = await browser.newPage();
    await page.goto('https://example.com');
    await page.screenshot({ path: '/tmp/playwright_screenshot.png', fullPage: true });
    console.log(await page.title());
    await browser.close();
})();
```

Run via Node:
```sh
node example.js
```

### Puppeteer Automation

Puppeteer automatically manages headless Chromium binaries:

```javascript
// test-puppeteer.js
const puppeteer = require('puppeteer');

(async () => {
    const browser = await puppeteer.launch({ headless: 'new' });
    const page = await browser.newPage();
    await page.goto('https://example.com');
    await page.screenshot({ path: '/tmp/puppeteer_screenshot.png' });
    await browser.close();
})();
```

## Best Practices
- **Always use headless flags**: Pass `--headless=new` for Chromium or ensure `headless: true` is configured in Playwright/Puppeteer configurations.
- **Output storage**: Write test screenshots and artifacts to `/tmp` or the agent workspace.
- **Resource cleanup**: Always close browser contexts (`browser.close()`) to avoid orphaned browser processes.
