#!/bin/bash
set -e

if [ "${PA_CONTAINER_DESKTOP}" != "true" ]; then
    exit 0
fi

mkdir -p /run/user/1000 /tmp/.X11-unix
chown agent:agent /run/user/1000
chmod 700 /run/user/1000
chmod 1777 /tmp/.X11-unix

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
