---
name: chromium
description: Launch, automate, and test web applications using Chrome for Testing in headless or virtual desktop mode.
---

# Chromium & Browser Automation

## Common Workflows

### 1. Headless Web Page Dump
```bash
chromium --headless --dump-dom https://example.com
```

### 2. Capture Web Page Screenshot
```bash
chromium --headless --screenshot=/tmp/page.png --window-size=1280,800 https://example.com
```

### 3. Launch on Virtual Desktop
```bash
agent-desktop launch chromium https://example.com
```
