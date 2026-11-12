#!/bin/bash
# Staging recipe for the virtual-desktop x11 display backend feature:
# Xvfb display server, x11vnc VNC server, openbox window manager, and
# xdotool/wmctrl/ImageMagick automation tooling.
set -euo pipefail

PA_STAGE="${PA_STAGE:-/out}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mkdir -p \
    "${PA_STAGE}/usr/bin" \
    "${PA_STAGE}/usr/lib64" \
    "${PA_STAGE}/usr/local/share/pa-container/entrypoint.d/root" \
    "${PA_STAGE}/usr/local/share/pa-container/entrypoint.d/agent"

# Stage display stack binaries with their shared library closures.
# 'import' is the ImageMagick screenshot backend used by agent-desktop on X11.
for bin in Xvfb x11vnc openbox xdotool wmctrl import; do
    bin_path="$(command -v "${bin}" || true)"
    if [ -z "${bin_path}" ]; then
        echo "ERROR: x11 feature requires '${bin}', which was not found in the build stage" >&2
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
