#!/bin/bash
set -euo pipefail

PA_STAGE="${PA_STAGE:-/out}"
mkdir -p "${PA_STAGE}/usr/local/bin" "${PA_STAGE}/etc/xdg/labwc" "${PA_STAGE}/usr/share/novnc" "${PA_STAGE}/usr/bin"

if [ -f /build/agent-desktop ]; then
    install -m 0755 /build/agent-desktop "${PA_STAGE}/usr/local/bin/agent-desktop"
fi

if [ -d /build/config/labwc ]; then
    cp -a /build/config/labwc/* "${PA_STAGE}/etc/xdg/labwc/"
fi

if [ -d /build/entrypoint.d/root ]; then
    mkdir -p "${PA_STAGE}/usr/local/share/pa-container/entrypoint.d/root"
    cp -a /build/entrypoint.d/root/* "${PA_STAGE}/usr/local/share/pa-container/entrypoint.d/root/"
    chmod +x "${PA_STAGE}/usr/local/share/pa-container/entrypoint.d/root/"*.sh 2>/dev/null || true
fi

if [ -d /build/entrypoint.d/agent ]; then
    mkdir -p "${PA_STAGE}/usr/local/share/pa-container/entrypoint.d/agent"
    cp -a /build/entrypoint.d/agent/* "${PA_STAGE}/usr/local/share/pa-container/entrypoint.d/agent/"
    chmod +x "${PA_STAGE}/usr/local/share/pa-container/entrypoint.d/agent/"*.sh 2>/dev/null || true
fi

# Stage labwc, wayvnc, novnc, and Xwayland binaries
for bin in labwc wayvnc Xwayland wlr-randr grim slurp websockify; do
    p="$(command -v "$bin" || true)"
    if [ -n "$p" ]; then
        cp -a "$p" "${PA_STAGE}/usr/bin/"
    fi
done

if [ -d /usr/share/novnc ]; then
    cp -a /usr/share/novnc/* "${PA_STAGE}/usr/share/novnc/"
fi
printf '{"reconnect": true, "reconnect_delay": 1000}\n' > "${PA_STAGE}/usr/share/novnc/mandatory.json"

stage_record "virtual-desktop" "2.0.0"
