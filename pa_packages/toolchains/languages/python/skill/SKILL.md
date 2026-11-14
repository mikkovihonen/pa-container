---
name: python
description: Execute Python scripts, manage virtual environments, install packages via uv, and run Python test suites.
---

# Python & uv Environment

## Overview

The container ships with CPython 3.14, `uv` (fast package and project manager), and `pip`.

- **Interpreter**: `/usr/local/bin/python3`
- **Package Manager**: `/usr/local/bin/uv`
- **System Certificates**: Automatically trusted via `UV_SYSTEM_CERTS=1`

## Recommended Workflows

### 1. Package Management with uv
Use `uv` for lightning-fast environment and dependency operations:
```bash
uv venv
uv pip install -r requirements.txt
uv run pytest
```

### 2. Running Ad-hoc Scripts
Execute single-file scripts with isolated dependencies:
```bash
uv run --with requests python -c 'import requests; print(requests.__version__)'
```
