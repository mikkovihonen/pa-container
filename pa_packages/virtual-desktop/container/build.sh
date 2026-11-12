#!/bin/bash
# Shared staging recipe for the virtual-desktop package (backend-independent).
# Stages the agent-desktop CLI, noVNC web client, websockify, fonts, and the
# software-rendering stack used by the wayland/x11 display backend features.
set -euo pipefail

PA_STAGE="${PA_STAGE:-/out}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mkdir -p \
    "${PA_STAGE}/usr/local/bin" \
    "${PA_STAGE}/usr/bin" \
    "${PA_STAGE}/usr/share/novnc" \
    "${PA_STAGE}/usr/lib64"

# 1. Stage the shared agent-desktop automation CLI
install -m 0755 "${SCRIPT_DIR}/agent-desktop" "${PA_STAGE}/usr/local/bin/agent-desktop"

# 2. Stage the noVNC web client with auto-reconnect policy
if [ -d /usr/share/novnc ]; then
    cp -a /usr/share/novnc/* "${PA_STAGE}/usr/share/novnc/"
fi
printf '{"reconnect": true, "reconnect_delay": 1000}\n' > "${PA_STAGE}/usr/share/novnc/mandatory.json"

# 3. Stage websockify (serves noVNC and proxies websocket clients to the VNC server)
ws_bin="$(command -v websockify || true)"
if [ -n "${ws_bin}" ]; then
    install -m 0755 "${ws_bin}" "${PA_STAGE}/usr/bin/websockify"
    # The console script imports the websockify python package; stage it for
    # the matching interpreter in the agent base image.
    for pydir in /usr/lib/python3*/site-packages; do
        if [ -d "${pydir}/websockify" ]; then
            mkdir -p "${PA_STAGE}${pydir}"
            cp -a "${pydir}/websockify" "${PA_STAGE}${pydir}/"
        fi
    done
fi

# 4. Stage core fonts for GUI application text rendering
for font_dir in /usr/share/fonts/dejavu /usr/share/fonts/liberation; do
    if [ -d "${font_dir}" ]; then
        mkdir -p "${PA_STAGE}${font_dir}"
        cp -a "${font_dir}/." "${PA_STAGE}${font_dir}/"
    fi
done

# 5. Stage Mesa software DRI drivers (llvmpipe/swrast) loaded at runtime by dlopen
if [ -d /usr/lib64/dri ]; then
    mkdir -p "${PA_STAGE}/usr/lib64/dri"
    cp -a /usr/lib64/dri/. "${PA_STAGE}/usr/lib64/dri/"
fi

# 6. Stage X.Org server modules loaded dynamically by Xwayland (wayland feature)
#    and Xvfb (x11 feature)
if [ -d /usr/lib64/xorg/modules ]; then
    mkdir -p "${PA_STAGE}/usr/lib64/xorg/modules"
    cp -a /usr/lib64/xorg/modules/. "${PA_STAGE}/usr/lib64/xorg/modules/"
fi

stage_record "virtual-desktop" "2.1.0"
