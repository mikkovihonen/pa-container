#!/bin/bash
# Install Git Model Context Protocol (MCP) server
set -euo pipefail

PA_STAGE="${PA_STAGE:-/out}"

echo "=== Installing mcp-server-git ==="
python3 -m pip install --prefix=/usr/local --root-user-action=ignore --root "${PA_STAGE}" --ignore-installed mcp-server-git

"${PA_STAGE}/usr/local/bin/mcp-server-git" --help >/dev/null 2>&1 || true
stage_record "mcp-server-git" "latest"
