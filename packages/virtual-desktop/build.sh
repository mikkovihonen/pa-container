#!/bin/bash
set -euo pipefail

PA_STAGE="${PA_STAGE:-/out}"
mkdir -p "${PA_STAGE}/usr/local/bin" "${PA_STAGE}/etc/xdg/labwc"

if [ -f /build/agent-desktop ]; then
    install -m 0755 /build/agent-desktop "${PA_STAGE}/usr/local/bin/agent-desktop"
fi

if [ -d /build/config/labwc ]; then
    cp -a /build/config/labwc/* "${PA_STAGE}/etc/xdg/labwc/"
fi
