#!/bin/bash
# Download, verify, and stage the Claude Code agent binary.
#
# Run from coding-agent-builder/Containerfile, as root, at image build time.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMMON_SH="${SCRIPT_DIR}/../../common.sh"
[ -f "${COMMON_SH}" ] || COMMON_SH="/build/common.sh"
# shellcheck source=/dev/null
source "${COMMON_SH}"

require_env CLAUDE_CODE_VERSION CLAUDE_CODE_SHA256_AMD64 CLAUDE_CODE_SHA256_ARM64

case "$(deb_arch)" in
    amd64) claude_sha="${CLAUDE_CODE_SHA256_AMD64}"; claude_arch="x64" ;;
    arm64) claude_sha="${CLAUDE_CODE_SHA256_ARM64}"; claude_arch="arm64" ;;
    *)
        echo "ERROR: no pinned Claude Code archive for '$(deb_arch)'" >&2
        exit 1
        ;;
esac

claude_tarball="claude-code-linux-${claude_arch}-${CLAUDE_CODE_VERSION}.tgz"
claude_url="https://registry.npmjs.org/@anthropic-ai/claude-code-linux-${claude_arch}/-/claude-code-linux-${claude_arch}-${CLAUDE_CODE_VERSION}.tgz"

fetch_verified "${claude_url}" "${claude_sha}" "/tmp/${claude_tarball}"

mkdir -p "${PI_STAGE}/usr/local/bin"
tar -xzf "/tmp/${claude_tarball}" --strip-components=1 -C "${PI_STAGE}/usr/local/bin" "package/claude"
chmod 755 "${PI_STAGE}/usr/local/bin/claude"
ln -s "claude" "${PI_STAGE}/usr/local/bin/claude-code"
rm -f "/tmp/${claude_tarball}"

stage_record "claude-code" "${CLAUDE_CODE_VERSION}"
