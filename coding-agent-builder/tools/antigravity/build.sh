#!/bin/bash
# Download, verify, and stage the Google Antigravity CLI (agy) binary.
#
# Run from coding-agent-builder/Containerfile, as root, at image build time.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMMON_SH="${SCRIPT_DIR}/../../common.sh"
[ -f "${COMMON_SH}" ] || COMMON_SH="/build/common.sh"
# shellcheck source=/dev/null
source "${COMMON_SH}"

require_env ANTIGRAVITY_VERSION ANTIGRAVITY_BUILD_ID ANTIGRAVITY_SHA256_AMD64 ANTIGRAVITY_SHA256_ARM64

case "$(deb_arch)" in
    amd64)
        antigravity_sha="${ANTIGRAVITY_SHA256_AMD64}"
        antigravity_path="linux-x64/cli_linux_x64.tar.gz"
        ;;
    arm64)
        antigravity_sha="${ANTIGRAVITY_SHA256_ARM64}"
        antigravity_path="linux-arm/cli_linux_arm64.tar.gz"
        ;;
    *)
        echo "ERROR: no pinned Antigravity CLI archive for '$(deb_arch)'" >&2
        exit 1
        ;;
esac

antigravity_tarball="antigravity-${ANTIGRAVITY_VERSION}-$(deb_arch).tar.gz"
antigravity_url="https://storage.googleapis.com/antigravity-public/antigravity-cli/${ANTIGRAVITY_VERSION}-${ANTIGRAVITY_BUILD_ID}/${antigravity_path}"

fetch_verified "${antigravity_url}" "${antigravity_sha}" "/tmp/${antigravity_tarball}"

mkdir -p "${PA_STAGE}/usr/local/bin"
tar -xzf "/tmp/${antigravity_tarball}" -C "${PA_STAGE}/usr/local/bin"
chmod 755 "${PA_STAGE}/usr/local/bin/antigravity"
ln -sf antigravity "${PA_STAGE}/usr/local/bin/agy"
rm -f "/tmp/${antigravity_tarball}"

stage_record "antigravity" "${ANTIGRAVITY_VERSION}"
