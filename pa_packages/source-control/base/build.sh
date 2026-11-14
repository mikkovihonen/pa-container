#!/bin/bash
# Install and stage base source-control capability hooks.
#
# Run from ACP package builder, as root, at image build time.
set -euo pipefail
PA_STAGE="${PA_STAGE:-/out}"

if [ -d /build/entrypoint.d/agent ]; then
    mkdir -p "${PA_STAGE}/usr/local/share/pa-container/entrypoint.d/agent"
    cp -a /build/entrypoint.d/agent/* "${PA_STAGE}/usr/local/share/pa-container/entrypoint.d/agent/"
    chmod +x "${PA_STAGE}/usr/local/share/pa-container/entrypoint.d/agent/"*.sh 2>/dev/null || true
fi

stage_record "source-control" "1.0.0"
