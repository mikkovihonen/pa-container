#!/bin/bash
# Download, verify, and stage the Anthropic Claude Code release binary.
set -euo pipefail
PA_STAGE="${PA_STAGE:-/out}"

CLAUDE_VERSION="${CLAUDE_CODE_VERSION:-${CLAUDE_VERSION:-}}"
export CLAUDE_VERSION
require_env CLAUDE_VERSION CLAUDE_SHA256_AMD64 CLAUDE_SHA256_ARM64

case "$(deb_arch)" in
    amd64) claude_sha="${CLAUDE_SHA256_AMD64}"; claude_arch="linux-x64" ;;
    arm64) claude_sha="${CLAUDE_SHA256_ARM64}"; claude_arch="linux-arm64" ;;
    *)
        echo "ERROR: no pinned Claude Code binary for '$(deb_arch)'" >&2
        exit 1
        ;;
esac

claude_tarball="claude-code-${claude_arch}-${CLAUDE_VERSION}.tgz"
claude_url="https://registry.npmjs.org/@anthropic-ai/claude-code-${claude_arch}/-/${claude_tarball}"

fetch_verified "${claude_url}" "${claude_sha}" "/tmp/${claude_tarball}"

mkdir -p "${PA_STAGE}/usr/local/bin"
tar -C "${PA_STAGE}/usr/local/bin" --strip-components=1 -xzf "/tmp/${claude_tarball}" "package/claude"
chmod 0755 "${PA_STAGE}/usr/local/bin/claude"
rm -f "/tmp/${claude_tarball}"

"${PA_STAGE}/usr/local/bin/claude" --version
stage_record "claude" "${CLAUDE_VERSION}"
