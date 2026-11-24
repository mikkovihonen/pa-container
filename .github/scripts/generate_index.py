#!/usr/bin/env python3
"""Generate docs/index.md using pa docs index."""

import subprocess
import sys

res = subprocess.run(["cargo", "run", "--quiet", "--bin", "pa", "--", "docs", "index"])
sys.exit(res.returncode)
