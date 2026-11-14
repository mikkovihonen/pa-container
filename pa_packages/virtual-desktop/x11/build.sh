#!/bin/bash
# Staging recipe for the virtual-desktop x11 display backend feature.
#
# The display stack (Xvfb display server, x11vnc VNC server, openbox window
# manager, xdotool/wmctrl/ImageMagick automation tooling, and the xkbcomp +
# xkeyboard-config keymap data Xvfb requires) is declared as distro packages
# in package.yaml and installed into the TARGET image by the package builder.
# This script stages only the backend entrypoint hooks; it must not hand-stage
# binaries, shared-library closures, or XKB data from the build stage (cp -a
# on /usr/share/X11/xkb copies a dangling symlink instead of the data).
set -euo pipefail

PA_STAGE="${PA_STAGE:-/out}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mkdir -p \
    "${PA_STAGE}/usr/local/share/pa-container/entrypoint.d/root" \
    "${PA_STAGE}/usr/local/share/pa-container/entrypoint.d/agent"

# Stage x11 backend entrypoint hooks. The wayland backend stages the same
# hook filenames; refuse to mix the two backends into one image.
_staged_root_hook="${PA_STAGE}/usr/local/share/pa-container/entrypoint.d/root/61-desktop.sh"
if [ -f "${_staged_root_hook}" ] && grep -q '!= "wayland"' "${_staged_root_hook}"; then
    echo "ERROR: the wayland and x11 display backends are mutually exclusive; enable exactly one" >&2
    exit 1
fi
install -m 0755 "${SCRIPT_DIR}/entrypoint.d/root/61-desktop.sh" \
    "${PA_STAGE}/usr/local/share/pa-container/entrypoint.d/root/61-desktop.sh"
install -m 0755 "${SCRIPT_DIR}/entrypoint.d/agent/61-desktop.sh" \
    "${PA_STAGE}/usr/local/share/pa-container/entrypoint.d/agent/61-desktop.sh"

stage_record "xvfb" "distro"
stage_record "x11vnc" "distro"
stage_record "openbox" "distro"
