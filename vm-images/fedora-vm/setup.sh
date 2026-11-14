#!/usr/bin/env bash
# Provisioning script for Fedora Factory VM guest (Incus / KVM)
set -euo pipefail

echo "=== Provisioning Fedora Factory VM ==="

# Install required system packages
dnf install -y bubblewrap nftables git python3 python3-pip

# Prepare directories
mkdir -p /opt/pa/bin /opt/pa/certs /opt/pa/packages /var/pa-vault
chmod 755 /opt/pa
chmod 700 /var/pa-vault

# Enable and start pa-agentd systemd service
cat << 'EOF' > /etc/systemd/system/pa-agentd.service
[Unit]
Description=PA-Container 2.0 Guest Agent Daemon
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 -m guest_daemon.daemon --socket /var/run/pa-agentd.sock
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable pa-agentd.service || true

echo "=== Fedora Factory VM Provisioning Complete ==="
