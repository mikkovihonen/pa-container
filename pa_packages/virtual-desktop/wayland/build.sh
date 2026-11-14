#!/bin/bash
# Staging recipe for the virtual-desktop wayland display backend feature.
#
# The display stack (labwc compositor with Xwayland compatibility, wayvnc VNC
# server, wlr-randr/grim/slurp/xdotool/wtype automation tooling, Mesa GL, and
# the xkbcomp + xkeyboard-config keymap data Xwayland requires) is declared as
# distro packages in package.yaml and installed into the TARGET image by the
# package builder. This script stages only the compositor configuration and
# the backend entrypoint hooks; it must not hand-stage binaries,
# shared-library closures, or XKB data from the build stage.
set -euo pipefail

PA_STAGE="${PA_STAGE:-/out}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mkdir -p \
    "${PA_STAGE}/etc/xdg/labwc" \
    "${PA_STAGE}/usr/local/share/pa-container/entrypoint.d/root" \
    "${PA_STAGE}/usr/local/share/pa-container/entrypoint.d/agent"

# Stage labwc compositor configuration (exit-preventing keybinds and menus)
if [ -d "${SCRIPT_DIR}/config/labwc" ]; then
    cp -a "${SCRIPT_DIR}/config/labwc/." "${PA_STAGE}/etc/xdg/labwc/"
fi

# Stage wayland backend entrypoint hooks. The x11 backend stages the same
# hook filenames; refuse to mix the two backends into one image.
_staged_root_hook="${PA_STAGE}/usr/local/share/pa-container/entrypoint.d/root/61-desktop.sh"
if [ -f "${_staged_root_hook}" ] && grep -q '!= "x11"' "${_staged_root_hook}"; then
    echo "ERROR: the wayland and x11 display backends are mutually exclusive; enable exactly one" >&2
    exit 1
fi
install -m 0755 "${SCRIPT_DIR}/entrypoint.d/root/61-desktop.sh" \
    "${PA_STAGE}/usr/local/share/pa-container/entrypoint.d/root/61-desktop.sh"
install -m 0755 "${SCRIPT_DIR}/entrypoint.d/agent/61-desktop.sh" \
    "${PA_STAGE}/usr/local/share/pa-container/entrypoint.d/agent/61-desktop.sh"

stage_record "labwc" "distro"
stage_record "wayvnc" "distro"
stage_record "xwayland" "distro"
