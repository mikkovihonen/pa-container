#!/usr/bin/env python3
"""Validate version consistency using pa version check."""

import subprocess
import sys

res = subprocess.run(["cargo", "run", "--quiet", "--bin", "pa", "--", "version", "check", *sys.argv[1:]])
sys.exit(res.returncode)
