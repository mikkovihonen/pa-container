#!/bin/bash
# Download, verify, and stage the Google Antigravity CLI (agy) binary
# and the Antigravity ACP runtime required by T3 Code.
#
# Run from coding-agent-builder/Containerfile, as root, at image build time.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMMON_SH="${SCRIPT_DIR}/../../common.sh"
[ -f "${COMMON_SH}" ] || COMMON_SH="/build/common.sh"
# shellcheck source=/dev/null
source "${COMMON_SH}"

require_env ANTIGRAVITY_VERSION ANTIGRAVITY_BUILD_ID ANTIGRAVITY_SHA256_AMD64 ANTIGRAVITY_SHA256_ARM64 \
            ANTIGRAVITY_ACP_VERSION ANTIGRAVITY_ACP_SHA256_AMD64 ANTIGRAVITY_ACP_SHA256_ARM64

case "$(deb_arch)" in
    amd64)
        antigravity_sha="${ANTIGRAVITY_SHA256_AMD64}"
        antigravity_path="linux-x64/cli_linux_x64.tar.gz"
        acp_sha="${ANTIGRAVITY_ACP_SHA256_AMD64}"
        acp_zip="agy-acp-server-${ANTIGRAVITY_ACP_VERSION}-linux-x86_64.zip"
        acp_url="https://dl.google.com/agy-extensions/releases/linux/${acp_zip}"
        acp_platform_arch="linux-x64"
        ;;
    arm64)
        antigravity_sha="${ANTIGRAVITY_SHA256_ARM64}"
        antigravity_path="linux-arm/cli_linux_arm64.tar.gz"
        acp_sha="${ANTIGRAVITY_ACP_SHA256_ARM64}"
        acp_zip="agy-acp-server-${ANTIGRAVITY_ACP_VERSION}-linux-arm64.zip"
        acp_url="https://dl.google.com/agy-extensions/releases/linux/${acp_zip}"
        acp_platform_arch="linux-arm64"
        ;;
    *)
        echo "ERROR: no pinned Antigravity archive for '$(deb_arch)'" >&2
        exit 1
        ;;
esac

# 1. Antigravity CLI (antigravity / agy)
antigravity_tarball="antigravity-${ANTIGRAVITY_VERSION}-$(deb_arch).tar.gz"
antigravity_url="https://storage.googleapis.com/antigravity-public/antigravity-cli/${ANTIGRAVITY_VERSION}-${ANTIGRAVITY_BUILD_ID}/${antigravity_path}"

fetch_verified "${antigravity_url}" "${antigravity_sha}" "/tmp/${antigravity_tarball}"

mkdir -p "${PA_STAGE}/usr/local/bin"
tar -xzf "/tmp/${antigravity_tarball}" -C "${PA_STAGE}/usr/local/bin"
chmod 755 "${PA_STAGE}/usr/local/bin/antigravity"
ln -sf antigravity "${PA_STAGE}/usr/local/bin/agy"
rm -f "/tmp/${antigravity_tarball}"

# 2. Antigravity ACP runtime for T3 Code (agy_acp_server.par & localharness_external)
fetch_verified "${acp_url}" "${acp_sha}" "/tmp/${acp_zip}"

unzip -q -o "/tmp/${acp_zip}" agy_acp_server.par localharness_external -d "${PA_STAGE}/usr/local/bin"
chmod 755 "${PA_STAGE}/usr/local/bin/agy_acp_server.par" "${PA_STAGE}/usr/local/bin/localharness_external"
rm -f "/tmp/${acp_zip}"

# 3. Pre-stage T3 managed runtime metadata so T3 detects Antigravity out-of-the-box
acp_stage_dir="${PA_STAGE}/usr/local/share/t3/tools/antigravity-acp/${acp_platform_arch}"
acp_version_dir="${acp_stage_dir}/versions/${acp_sha}"
mkdir -p "${acp_version_dir}"

ln -sf /usr/local/bin/agy_acp_server.par "${acp_version_dir}/agy_acp_server.par"
ln -sf /usr/local/bin/localharness_external "${acp_version_dir}/localharness_external"

exe_bytes=$(stat -c%s "${PA_STAGE}/usr/local/bin/agy_acp_server.par")
harness_bytes=$(stat -c%s "${PA_STAGE}/usr/local/bin/localharness_external")

cat << EOF > "${acp_version_dir}/.install-complete.json"
{
  "releaseId": "${acp_sha}",
  "version": "${ANTIGRAVITY_ACP_VERSION}",
  "executable": {
    "name": "agy_acp_server.par",
    "bytes": ${exe_bytes}
  },
  "harness": {
    "name": "localharness_external",
    "bytes": ${harness_bytes}
  }
}
EOF

cat << EOF > "${acp_stage_dir}/active.json"
{
  "releaseId": "${acp_sha}"
}
EOF

stage_record "antigravity" "${ANTIGRAVITY_VERSION}"
