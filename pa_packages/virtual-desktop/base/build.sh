#!/bin/bash
# Staging recipe for the virtual-desktop package (backend-independent).
#
# The shared runtime stack (noVNC web client, websockify, Mesa DRI drivers, and
# core fonts) is declared as distro packages in package.yaml and installed
# into the TARGET image by the package builder. This script stages only the
# shared agent-desktop automation CLI and the noVNC auto-reconnect policy.
set -euo pipefail

PA_STAGE="${PA_STAGE:-/out}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mkdir -p \
    "${PA_STAGE}/usr/local/bin" \
    "${PA_STAGE}/usr/share/novnc"

# 1. Stage the shared agent-desktop automation CLI
install -m 0755 "${SCRIPT_DIR}/agent-desktop" "${PA_STAGE}/usr/local/bin/agent-desktop"

# 2. Stage the noVNC auto-reconnect policy (the web client itself comes from
#    the novnc distro package installed into the target image)
printf '{"reconnect": true, "reconnect_delay": 1000}\n' > "${PA_STAGE}/usr/share/novnc/mandatory.json"

stage_record "virtual-desktop" "2.1.0"
