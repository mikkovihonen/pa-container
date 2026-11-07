#!/bin/bash
# Download, verify, and stage Chrome for Testing binary and wrapper.
#
# Run from coding-agent-builder/Containerfile, as root, at image build time.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMMON_SH="${SCRIPT_DIR}/../../common.sh"
[ -f "${COMMON_SH}" ] || COMMON_SH="/build/common.sh"
# shellcheck source=/dev/null
source "${COMMON_SH}"

require_env CHROMIUM_VERSION CHROMIUM_SHA256_AMD64 CHROMIUM_SHA256_ARM64

case "$(deb_arch)" in
    amd64)
        chrome_sha="${CHROMIUM_SHA256_AMD64}"
        chrome_arch="linux64"
        dir_name="chrome-linux64"
        ;;
    arm64)
        chrome_sha="${CHROMIUM_SHA256_ARM64}"
        chrome_arch="linux-arm64"
        dir_name="chrome-linux-arm64"
        ;;
    *)
        echo "ERROR: no pinned Chromium archive for '$(deb_arch)'" >&2
        exit 1
        ;;
esac

zip_file="chrome-${chrome_arch}.zip"
chrome_url="https://storage.googleapis.com/chrome-for-testing-public/${CHROMIUM_VERSION}/${chrome_arch}/${zip_file}"

fetch_verified "${chrome_url}" "${chrome_sha}" "/tmp/${zip_file}"

mkdir -p "${PI_STAGE}/usr/local/lib/chromium" "/tmp/chrome_unpack"
unzip -q "/tmp/${zip_file}" -d "/tmp/chrome_unpack"
cp -a "/tmp/chrome_unpack/${dir_name}"/* "${PI_STAGE}/usr/local/lib/chromium/"
rm -rf "/tmp/${zip_file}" "/tmp/chrome_unpack"

mkdir -p "${PI_STAGE}/usr/local/bin"

cat <<'EOF' > "${PI_STAGE}/usr/local/bin/chromium"
#!/bin/bash
# Wrapper script for containerized Chromium / Chrome for Testing.
set -euo pipefail

CHROME_BIN="/usr/local/lib/chromium/chrome"

# Initialize user NSS DB with mitmproxy CA if certutil is available and CA exists
CA_CERT="/etc/pi-container-ca.crt"
if [ ! -f "${CA_CERT}" ]; then
    CA_CERT="/usr/local/share/ca-certificates/extra/mitmproxy-ca-cert.crt"
fi

if [ -f "${CA_CERT}" ] && command -v certutil >/dev/null 2>&1; then
    NSS_DIR="${HOME:-/home/agent}/.pki/nssdb"
    if [ ! -d "${NSS_DIR}" ] || [ ! -f "${NSS_DIR}/cert9.db" ]; then
        mkdir -p "${NSS_DIR}"
        certutil -d "sql:${NSS_DIR}" -N --empty-password >/dev/null 2>&1 || true
        certutil -d "sql:${NSS_DIR}" -A -t "C,," -n "mitmproxy" -i "${CA_CERT}" >/dev/null 2>&1 || true
    fi
fi

# Detect Wayland vs X11
EXTRA_FLAGS=()
if [ -n "${WAYLAND_DISPLAY:-}" ]; then
    EXTRA_FLAGS+=(
        "--ozone-platform-hint=auto"
        "--enable-features=UseOzonePlatform,WaylandWindowDecorations"
    )
fi

# Software rasterization fallback if DRI device is unavailable
if [ ! -e /dev/dri ]; then
    EXTRA_FLAGS+=(
        "--use-gl=angle"
        "--use-angle=swiftshader"
    )
fi

exec "${CHROME_BIN}" \
    --no-sandbox \
    --disable-dev-shm-usage \
    "${EXTRA_FLAGS[@]}" \
    "$@"
EOF

chmod 0755 "${PI_STAGE}/usr/local/bin/chromium"
ln -sf "/usr/local/bin/chromium" "${PI_STAGE}/usr/local/bin/google-chrome"

stage_record "chromium" "${CHROMIUM_VERSION}"
