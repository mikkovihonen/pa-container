#!/bin/bash
# Wayland display backend supervisor: labwc compositor + wayvnc VNC server.
# Runs as a background auto-recovery loop sourced from the agent entrypoint.
set -e

if [ "${PA_CONTAINER_DESKTOP}" != "true" ]; then
    return 0 2>/dev/null || exit 0
fi

if [ "${PA_DESKTOP_BACKEND}" != "wayland" ]; then
    return 0 2>/dev/null || exit 0
fi

if [ ! -e /dev/dri ]; then
    export GALLIUM_DRIVER=llvmpipe
    export LP_NUM_THREADS=$(nproc 2>/dev/null || echo 4)
    export MESA_GL_VERSION_OVERRIDE=4.5
    export MESA_GLSL_VERSION_OVERRIDE=450
    export LIBGL_ALWAYS_SOFTWARE=1
fi

export WLR_BACKENDS=headless
export WLR_LIBINPUT_NO_DEVICES=1
export WAYLAND_DISPLAY=wayland-0
export DISPLAY=:0
export XDG_RUNTIME_DIR=/run/user/1000

# Seed labwc user configuration from /etc/xdg/labwc if not present
mkdir -p /home/agent/.config/labwc
if [ -d /etc/xdg/labwc ]; then
    cp -n /etc/xdg/labwc/* /home/agent/.config/labwc/ 2>/dev/null || true
fi

_res="${PA_DESKTOP_RESOLUTION:-1920x1080}"
_wayvnc_gpu_arg=""
if [ -e /dev/dri ]; then
    _wayvnc_gpu_arg="--gpu"
fi

# Supervise labwc and wayvnc so the desktop session automatically recovers if exited
(
    while true; do
        rm -f "$XDG_RUNTIME_DIR/wayland-0" "$XDG_RUNTIME_DIR/wayland-0.lock" 2>/dev/null || true
        labwc -s /bin/true >/dev/null 2>&1 &
        _labwc_pid=$!

        # Wait up to 5 seconds for wayland-0 socket to become available
        for _ in $(seq 1 50); do
            if [ -S "$XDG_RUNTIME_DIR/wayland-0" ]; then
                break
            fi
            sleep 0.1
        done

        # Configure headless output resolution
        if command -v wlr-randr >/dev/null 2>&1; then
            wlr-randr --output HEADLESS-1 --mode "${_res}@60Hz" 2>/dev/null || \
            wlr-randr --output HEADLESS-1 --custom-mode "${_res}@60Hz" 2>/dev/null || true
        fi

        # Start wayvnc attached to the compositor
        wayvnc --render-cursor ${_wayvnc_gpu_arg} 127.0.0.1 5900 >/dev/null 2>&1 &
        _wayvnc_pid=$!

        # Monitor compositor and VNC server; restart both if either terminates
        while kill -0 "$_labwc_pid" 2>/dev/null && kill -0 "$_wayvnc_pid" 2>/dev/null; do
            sleep 1
        done

        kill "$_labwc_pid" 2>/dev/null || true
        kill "$_wayvnc_pid" 2>/dev/null || true
        wait "$_labwc_pid" 2>/dev/null || true
        wait "$_wayvnc_pid" 2>/dev/null || true
        sleep 0.5
    done
) &
