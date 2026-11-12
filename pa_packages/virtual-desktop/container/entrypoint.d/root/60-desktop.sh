#!/bin/bash
set -e

if [ "${PA_CONTAINER_DESKTOP}" != "true" ]; then
    exit 0
fi

mkdir -p /run/user/1000 /tmp/.X11-unix
chown agent:agent /run/user/1000
chmod 700 /run/user/1000
chmod 1777 /tmp/.X11-unix

# Forward desktop resources into nested containers if containers.conf directory exists
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

# Managed Chromium policy: disable DoH, trust system / local CAs
mkdir -p /etc/chromium/policies/managed
cat <<'EOF' > /etc/chromium/policies/managed/00-pa-container.json
{
  "DnsOverHttpsMode": "off",
  "BuiltInDnsClientEnabled": false,
  "PromptForDownloadLocation": false
}
EOF

# Configure NSS DB system-wide if certutil is available
if command -v certutil >/dev/null 2>&1; then
    mkdir -p /etc/pki/nssdb
    certutil -d "sql:/etc/pki/nssdb" -N --empty-password >/dev/null 2>&1 || true
    if [ -f /usr/local/share/ca-certificates/extra/mitmproxy-ca-cert.crt ]; then
        certutil -d "sql:/etc/pki/nssdb" -A -t "C,," -n "mitmproxy" -i /usr/local/share/ca-certificates/extra/mitmproxy-ca-cert.crt >/dev/null 2>&1 || true
    fi
fi
