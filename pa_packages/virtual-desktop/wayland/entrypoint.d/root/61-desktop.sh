#!/bin/bash
set -e

if [ "${PA_CONTAINER_DESKTOP}" != "true" ]; then
    exit 0
fi

if [ "${PA_DESKTOP_BACKEND}" != "wayland" ]; then
    exit 0
fi

# Forward the wayland display resources into nested containers if
# containers.conf directory exists
if [ -d /etc/containers/containers.conf.d ]; then
    _dri_mount=""
    if [ -e /dev/dri ]; then
        _dri_mount=', "type=bind,source=/dev/dri,destination=/dev/dri"'
    fi
    cat <<EOF > /etc/containers/containers.conf.d/60-pa-container-desktop.conf
[containers]
mounts = [
  "type=bind,source=/run/user/1000/wayland-0,destination=/run/user/1000/wayland-0",
  "type=bind,source=/tmp/.X11-unix,destination=/tmp/.X11-unix",
  "type=bind,source=/dev/shm,destination=/dev/shm"${_dri_mount}
]
env = [
  "DISPLAY=:0",
  "WAYLAND_DISPLAY=wayland-0",
  "XDG_RUNTIME_DIR=/run/user/1000"
]
EOF
fi
