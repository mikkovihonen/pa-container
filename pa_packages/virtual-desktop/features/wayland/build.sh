#!/bin/bash
# Staging recipe for the virtual-desktop wayland display backend feature:
# labwc compositor, Xwayland, wayvnc VNC server, and wlr-randr/grim/slurp tooling.
set -euo pipefail

PA_STAGE="${PA_STAGE:-/out}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mkdir -p \
    "${PA_STAGE}/usr/bin" \
    "${PA_STAGE}/usr/lib64" \
    "${PA_STAGE}/etc/xdg/labwc" \
    "${PA_STAGE}/usr/local/share/pa-container/entrypoint.d/root" \
    "${PA_STAGE}/usr/local/share/pa-container/entrypoint.d/agent"

# Stage display stack binaries with their shared library closures.
# xdotool/wtype provide synthetic input for Xwayland and native Wayland clients.
for bin in labwc wayvnc Xwayland wlr-randr grim slurp xdotool wtype; do
    bin_path="$(command -v "${bin}" || true)"
    if [ -z "${bin_path}" ]; then
        echo "ERROR: wayland feature requires '${bin}', which was not found in the build stage" >&2
        exit 1
    fi
    install -m 0755 "${bin_path}" "${PA_STAGE}/usr/bin/${bin}"
    for lib in $(ldd "${bin_path}" | awk '{print $3}' | grep -E '^/lib|^/usr/lib' || true); do
        case "$(basename "${lib}")" in
            libc.so*|ld-linux*|libdl.so*|libpthread.so*|librt.so*)
                ;;
            *)
                real_lib="$(realpath "${lib}")"
                cp -a "${lib}"* "${PA_STAGE}/usr/lib64/" 2>/dev/null || true
                cp -a "${real_lib}"* "${PA_STAGE}/usr/lib64/" 2>/dev/null || true
                ;;
        esac
    done
done

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
