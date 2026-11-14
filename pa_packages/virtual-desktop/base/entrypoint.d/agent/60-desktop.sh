#!/bin/bash
# Shared virtual-desktop agent hook (backend-independent): initializes the
# agent NSS database and serves the noVNC web client via websockify. The
# display server supervisor itself is provided by the active backend feature
# hook (61-desktop.sh under features/wayland or features/x11).
set -e

if [ "${PA_CONTAINER_DESKTOP}" != "true" ]; then
    return 0 2>/dev/null || exit 0
fi

if [ -z "${PA_DESKTOP_BACKEND:-}" ]; then
    return 0 2>/dev/null || exit 0
fi

export DISPLAY="${DISPLAY:-:0}"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/1000}"

# Initialize agent user NSS DB
if command -v certutil >/dev/null 2>&1; then
    mkdir -p /home/agent/.pki/nssdb
    certutil -d "sql:/home/agent/.pki/nssdb" -N --empty-password >/dev/null 2>&1 || true
    if [ -f /etc/pa-container-ca.crt ]; then
        certutil -d "sql:/home/agent/.pki/nssdb" -A -t "C,," -n "mitmproxy" -i /etc/pa-container-ca.crt >/dev/null 2>&1 || true
    elif [ -f /usr/local/share/ca-certificates/extra/mitmproxy-ca-cert.crt ]; then
        certutil -d "sql:/home/agent/.pki/nssdb" -A -t "C,," -n "mitmproxy" -i /usr/local/share/ca-certificates/extra/mitmproxy-ca-cert.crt >/dev/null 2>&1 || true
    fi
fi

# Start websockify in the background once the backend VNC server (port 5900)
# accepts connections. It serves the noVNC web client and proxies websocket
# clients to the VNC server.
if command -v websockify >/dev/null 2>&1 && [ -d /usr/share/novnc ]; then
    (
        for _ in $(seq 1 150); do
            if (exec 3<>/dev/tcp/127.0.0.1/5900) 2>/dev/null; then
                break
            fi
            sleep 0.1
        done
        websockify --web /usr/share/novnc 6080 127.0.0.1:5900 >/dev/null 2>&1
    ) &
fi
