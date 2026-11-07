#!/bin/bash
# Download, verify, and stage the OpenCode agent binary.
#
# Run from coding-agent-builder/Containerfile, as root, at image build time.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMMON_SH="${SCRIPT_DIR}/../../common.sh"
[ -f "${COMMON_SH}" ] || COMMON_SH="/build/common.sh"
# shellcheck source=/dev/null
source "${COMMON_SH}"

require_env OPENCODE_VERSION OPENCODE_SHA256_AMD64 OPENCODE_SHA256_ARM64

case "$(deb_arch)" in
    amd64) opencode_sha="${OPENCODE_SHA256_AMD64}"; opencode_arch="x64" ;;
    arm64) opencode_sha="${OPENCODE_SHA256_ARM64}"; opencode_arch="arm64" ;;
    *)
        echo "ERROR: no pinned OpenCode archive for '$(deb_arch)'" >&2
        exit 1
        ;;
esac

opencode_tarball="cli-linux-${opencode_arch}-${OPENCODE_VERSION}.tgz"
opencode_url="https://registry.npmjs.org/@opencode/cli-linux-${opencode_arch}/-/cli-linux-${opencode_arch}-${OPENCODE_VERSION}.tgz"

fetch_verified "${opencode_url}" "${opencode_sha}" "/tmp/${opencode_tarball}"

mkdir -p "${PA_STAGE}/usr/local/bin"
tar -xzf "/tmp/${opencode_tarball}" --strip-components=2 -C "${PA_STAGE}/usr/local/bin" "package/bin/opencode"
chmod 755 "${PA_STAGE}/usr/local/bin/opencode"
rm -f "/tmp/${opencode_tarball}"

stage_record "opencode" "${OPENCODE_VERSION}"
