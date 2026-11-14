#!/bin/bash
# Staging recipe for Reverse Engineering MCP Server
set -euo pipefail
PA_STAGE="${PA_STAGE:-/out}"

mkdir -p "${PA_STAGE}/usr/local/bin" "${PA_STAGE}/usr/local/share/pa-container/packages/reverse-engineering/mcp"

SRC_DIR="$(dirname "$0")"
cp -a "${SRC_DIR}/server.py" "${PA_STAGE}/usr/local/share/pa-container/packages/reverse-engineering/mcp/server.py"

cat <<'EOF' > "${PA_STAGE}/usr/local/bin/re-mcp-server"
#!/usr/bin/env python3
import os
import sys

server_script = "/usr/local/share/pa-container/packages/reverse-engineering/mcp/server.py"
if not os.path.exists(server_script):
    server_script = os.path.join(os.path.dirname(__file__), "..", "share", "pa-container", "packages", "reverse-engineering", "mcp", "server.py")

os.execv(sys.executable, [sys.executable, server_script] + sys.argv[1:])
EOF
chmod 0755 "${PA_STAGE}/usr/local/bin/re-mcp-server"

stage_record "re-mcp-server" "1.0.0"
