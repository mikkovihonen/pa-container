#!/usr/bin/env bash
# Provisioning script for Fedora Factory VM guest (Incus / KVM)
set -euo pipefail

echo "=== Provisioning Fedora Factory VM ==="

# Install required system packages
dnf install -y bubblewrap nftables git

# Prepare directories & Git Vault
mkdir -p /opt/pa/bin /opt/pa/certs /opt/pa/packages /var/pa-vault
chmod 755 /opt/pa
chmod 777 /var/pa-vault
git config --system --add safe.directory '*' || true

# Performance & Headless Virtualization Tuning
systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target || true
systemctl disable --now packagekit.service || true
sysctl -w vm.swappiness=10 || true
mkdir -p /etc/cloud && touch /etc/cloud/cloud-init.disabled || true

# Deterministic non-interactive shell profile
cat << 'EOF' > /etc/profile.d/pa-env.sh
export PATH="/opt/pa/bin:$PATH"
export NONINTERACTIVE=1
export CI=true
EOF

if [ -f "$(dirname "$0")/../pa-agent-entrypoint" ]; then
    cp "$(dirname "$0")/../pa-agent-entrypoint" /opt/pa/bin/pa-agent-entrypoint
    chmod 755 /opt/pa/bin/pa-agent-entrypoint
fi

# Enable and start pa-agentd systemd service
cat << 'EOF' > /etc/systemd/system/pa-agentd.service
[Unit]
Description=PA-Container 2.0 Guest Agent Daemon
After=network.target

[Service]
Type=simple
ExecStart=/opt/pa/bin/pa-agentd --socket /var/run/pa-agentd.sock
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable pa-agentd.service || true

echo "=== Fedora Factory VM Provisioning Complete ==="
