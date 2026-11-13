#!/bin/bash
# Staging recipe for browser capability: Chrome for Testing and @playwright/mcp
set -euo pipefail
PA_STAGE="${PA_STAGE:-/out}"

mkdir -p "${PA_STAGE}/usr/local/bin" "${PA_STAGE}/usr/local/lib/chromium"

ARCH="$(uname -m)"
case "${ARCH}" in
    x86_64)
        chrome_sha="${CHROMIUM_SHA256_AMD64}"
        chrome_arch="linux64"
        dir_name="chrome-linux64"
        ;;
    aarch64|arm64)
        chrome_sha="${CHROMIUM_SHA256_ARM64}"
        chrome_arch="linux-arm64"
        dir_name="chrome-linux-arm64"
        ;;
    *)
        echo "ERROR: Unsupported architecture ${ARCH}" >&2
        exit 1
        ;;
esac

# 1. Install Chrome for Testing
zip_file="chrome-${chrome_arch}.zip"
chrome_url="https://storage.googleapis.com/chrome-for-testing-public/${CHROMIUM_VERSION}/${chrome_arch}/${zip_file}"

curl -fsSL -o "/tmp/${zip_file}" "${chrome_url}"
echo "${chrome_sha}  /tmp/${zip_file}" | sha256sum -c -

mkdir -p "/tmp/chrome_unpack"
unzip -q "/tmp/${zip_file}" -d "/tmp/chrome_unpack"
cp -a "/tmp/chrome_unpack/${dir_name}"/* "${PA_STAGE}/usr/local/lib/chromium/"
rm -rf "/tmp/${zip_file}" "/tmp/chrome_unpack"

cat <<'EOF' > "${PA_STAGE}/usr/local/bin/chromium"
#!/bin/bash
CHROME_BIN="/usr/local/lib/chromium/chrome"
exec "${CHROME_BIN}" --no-sandbox --disable-dev-shm-usage --disable-gpu "$@"
EOF
chmod 0755 "${PA_STAGE}/usr/local/bin/chromium"
ln -sf chromium "${PA_STAGE}/usr/local/bin/google-chrome"

# 2. Install @playwright/mcp via npm
echo "Installing @playwright/mcp..."
npm install -g --prefix="${PA_STAGE}/usr/local" "@playwright/mcp@${PLAYWRIGHT_MCP_VERSION}"

# 3. Verification
NODE_PATH="${PA_STAGE}/usr/local/lib/node_modules:${NODE_PATH:-}" "${PA_STAGE}/usr/local/bin/playwright-mcp" --version

echo "=== browser capability build complete ==="
