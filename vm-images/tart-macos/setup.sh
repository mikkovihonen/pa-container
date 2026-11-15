#!/usr/bin/env bash
# Provisioning script for Tart macOS Factory VM guest
set -euo pipefail

echo "=== Provisioning Tart macOS Factory VM ==="

# 1. Disable IPv6 on primary Ethernet interface for deterministic proxy routing
networksetup -setv6off Ethernet || true

# 2. Performance & Daemon Tuning (Spotlight, Power, CrashReporter, Gatekeeper)
echo "==> Applying macOS performance & headless virtualization tuning..."
mdutil -a -i off || true
mdutil -a -E || true
systemsetup -setcomputersleep Never || true
systemsetup -setdisplaysleep Never || true
systemsetup -setharddisksleep Never || true
defaults write com.apple.CrashReporter DialogType none || true
spctl --global-disable || true
defaults write com.apple.LaunchServices LSQuarantine -bool false || true
softwareupdate --schedule off || true
defaults write com.apple.SoftwareUpdate AutomaticCheckEnabled -bool false || true

# 3. Environment variables for non-interactive tools & deterministic Homebrew
cat << 'EOF' > /etc/zshenv
export PATH="/opt/pa/bin:/usr/local/bin:/opt/homebrew/bin:$PATH"
export HOMEBREW_NO_ANALYTICS=1
export HOMEBREW_NO_AUTO_UPDATE=1
export HOMEBREW_NO_INSTALL_CLEANUP=1
export HOMEBREW_NO_ENV_HINTS=1
export NONINTERACTIVE=1
EOF

# 4. Prepare directories & Git Vault
mkdir -p /opt/pa/bin /opt/pa/certs /opt/pa/packages /etc/pa/profiles /private/var/pa-vault /var/run/pa-ios
chmod 755 /opt/pa
chmod 777 /private/var/pa-vault
git config --system --add safe.directory '*' || true

# 5. Automated Headless Command Line Tools (CLT) Bootstrap
ensure_command_line_tools() {
    if ! xcode-select -p >/dev/null 2>&1; then
        echo "==> Xcode Command Line Tools missing. Triggering headless install-on-demand..."
        touch /tmp/.com.apple.dt.CommandLineTools.installondemand.in-progress
        CLT_LABEL=$(softwareupdate -l 2>/dev/null | grep -B 1 -E 'Command Line Tools' | awk -F'*' '/^   \*/ {print $2}' | sed -e 's/^ *Label: //' -e 's/^ *//' | sort -V | tail -n1 || true)
        if [ -n "$CLT_LABEL" ]; then
            softwareupdate -i "$CLT_LABEL" --verbose || true
            rm -f /tmp/.com.apple.dt.CommandLineTools.installondemand.in-progress
            xcode-select -s /Library/Developer/CommandLineTools || true
        fi
    fi
}
ensure_command_line_tools || true

if [ -f "$(dirname "$0")/../pa-agent-entrypoint" ]; then
    cp "$(dirname "$0")/../pa-agent-entrypoint" /opt/pa/bin/pa-agent-entrypoint
    chmod 755 /opt/pa/bin/pa-agent-entrypoint
fi

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
        <string>/opt/pa/bin/pa-agentd</string>
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
