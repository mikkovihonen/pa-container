#!/bin/bash
# X11 display backend supervisor: Xvfb display server + openbox window manager
# + x11vnc VNC server. Runs as a background auto-recovery loop sourced from the
# agent entrypoint.
set -e

if [ "${PA_CONTAINER_DESKTOP}" != "true" ]; then
    return 0 2>/dev/null || exit 0
fi

if [ "${PA_DESKTOP_BACKEND}" != "x11" ]; then
    return 0 2>/dev/null || exit 0
fi

if [ ! -e /dev/dri ]; then
    export GALLIUM_DRIVER=llvmpipe
    export LP_NUM_THREADS=$(nproc 2>/dev/null || echo 4)
    export MESA_GL_VERSION_OVERRIDE=4.5
    export MESA_GLSL_VERSION_OVERRIDE=450
    export LIBGL_ALWAYS_SOFTWARE=1
fi

export DISPLAY=:0
export XDG_RUNTIME_DIR=/run/user/1000

_res="${PA_DESKTOP_RESOLUTION:-1920x1080}"

# Supervise Xvfb, openbox, and x11vnc so the desktop session automatically
# recovers if any component terminates
(
    while true; do
        rm -f /tmp/.X11-unix/X0 /tmp/.X0-lock 2>/dev/null || true
        Xvfb :0 -ac -nolisten tcp -screen 0 "${_res}x24" >/dev/null 2>&1 &
        _xvfb_pid=$!

        # Wait up to 5 seconds for the X display socket to become available
        for _ in $(seq 1 50); do
            if [ -S /tmp/.X11-unix/X0 ]; then
                break
            fi
            sleep 0.1
        done

        # Start the window manager for focus handling and window stacking
        openbox >/dev/null 2>&1 &
        _wm_pid=$!

        # Start x11vnc attached to the Xvfb display
        x11vnc -display :0 -forever -shared -noxdamage -nopw -rfbport 5900 -quiet >/dev/null 2>&1 &
        _vnc_pid=$!

        # Monitor display server and VNC server; restart the stack if either terminates
        while kill -0 "$_xvfb_pid" 2>/dev/null && kill -0 "$_vnc_pid" 2>/dev/null; do
            sleep 1
        done

        kill "$_wm_pid" 2>/dev/null || true
        kill "$_xvfb_pid" 2>/dev/null || true
        kill "$_vnc_pid" 2>/dev/null || true
        wait "$_wm_pid" 2>/dev/null || true
        wait "$_xvfb_pid" 2>/dev/null || true
        wait "$_vnc_pid" 2>/dev/null || true
        sleep 0.5
    done
) &
