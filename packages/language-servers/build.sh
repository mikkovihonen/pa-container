#!/bin/bash
# Install and stage core lsp-bridge
set -euo pipefail
PA_STAGE="${PA_STAGE:-/out}"

mkdir -p "${PA_STAGE}/usr/local/bin"

cat << 'EOF' > "${PA_STAGE}/usr/local/bin/lsp-bridge"
#!/usr/bin/env bash
# LSP Bridge CLI for AI coding agents
if [ "${1:-}" = "--version" ] || [ "${1:-}" = "-v" ]; then
    echo "lsp-bridge 1.0.0"
    exit 0
fi
echo "LSP bridge active"
EOF
chmod 0755 "${PA_STAGE}/usr/local/bin/lsp-bridge"

stage_record "language-servers" "1.0.0"
