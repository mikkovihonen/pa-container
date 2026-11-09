---
name: node
description: Execute JavaScript and TypeScript applications, install dependencies with npm/npx, and run web development tooling.
---

# Node.js Runtime & npm

## Overview

The container provides Node.js 26 (LTS), `npm`, and `npx`.

- **Binary**: `/usr/local/bin/node`
- **Package Manager**: `/usr/local/bin/npm`
- **Runner**: `/usr/local/bin/npx`
- **System Certificates**: Configured automatically via `NODE_USE_SYSTEM_CA=1`

## Common Commands

### 1. Run Node Scripts
```bash
node app.js
```

### 2. Install Packages
```bash
npm install
npm test
```

### 3. One-off CLI Tool Execution
```bash
npx prettier --check .
```
