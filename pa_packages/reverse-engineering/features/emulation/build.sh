#!/bin/bash
# Staging recipe for Capstone, Unicorn, and Keystone emulation frameworks
set -euo pipefail
PA_STAGE="${PA_STAGE:-/out}"

echo "=== Installing Unicorn and Keystone Python bindings ==="
uv pip install --system --prefix="${PA_STAGE}/usr/local" unicorn keystone-engine

stage_record "emulation" "latest"
