#!/usr/bin/env bash
# Provisioning script for Tart macOS Factory VM guest
set -euo pipefail

echo "=== Provisioning Tart macOS Factory VM ==="

# Disable IPv6 on primary Ethernet interface for deterministic proxy routing
networksetup -setv6off Ethernet || true

# Prepare directories
mkdir -p /opt/pa/bin /opt/pa/certs /opt/pa/packages /etc/pa/profiles /private/var/pa-vault /var/run/pa-ios
chmod 755 /opt/pa
chmod 700 /private/var/pa-vault

# Install pa-agentd and pa-ios-runnerd launch daemons
cat << 'EOF' > /Library/LaunchDaemons/com.pa.agentd.plist
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.pa.agentd</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/python3</string>
        <string>-m</string>
        <string>guest_daemon.daemon</string>
        <string>--socket</string>
        <string>/var/run/pa-agentd.sock</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
</dict>
</plist>
EOF

echo "=== Tart macOS Factory VM Provisioning Complete ==="
