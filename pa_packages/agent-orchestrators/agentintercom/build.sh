#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_ROOT="${PA_STAGE:-${STAGE_DIR:-/out}}"

mkdir -p \
    "${TARGET_ROOT}/usr/local/bin" \
    "${TARGET_ROOT}/usr/local/share/pa-agentintercom" \
    "${TARGET_ROOT}/etc/profile.d"

install -m 0755 "${SCRIPT_DIR}/bin/agentintercom" "${TARGET_ROOT}/usr/local/bin/agentintercom"
install -m 0755 "${SCRIPT_DIR}/bin/pa-intercom-hook" "${TARGET_ROOT}/usr/local/bin/pa-intercom-hook"
install -m 0755 "${SCRIPT_DIR}/bin/pa-intercom-mcp" "${TARGET_ROOT}/usr/local/bin/pa-intercom-mcp"
install -m 0755 "${SCRIPT_DIR}/bin/pa-intercom-activate" "${TARGET_ROOT}/usr/local/bin/pa-intercom-activate"

cp -R "${SCRIPT_DIR}/extensions/"* "${TARGET_ROOT}/usr/local/share/pa-agentintercom/"

cat > "${TARGET_ROOT}/etc/profile.d/pa-agentintercom.sh" <<'EOF'
export PA_INTERCOM_DIR="${PA_INTERCOM_DIR:-/tmp/pa-intercom}"
if command -v pa-intercom-activate >/dev/null 2>&1; then
    pa-intercom-activate --quiet || true
fi
EOF
chmod 0644 "${TARGET_ROOT}/etc/profile.d/pa-agentintercom.sh"
