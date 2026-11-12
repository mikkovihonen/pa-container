#!/bin/bash
# Download, verify, and stage the OpenCode CLI release binary.
set -euo pipefail
PA_STAGE="${PA_STAGE:-/out}"

require_env OPENCODE_VERSION OPENCODE_SHA256_AMD64 OPENCODE_SHA256_ARM64

case "$(deb_arch)" in
    amd64) oc_sha="${OPENCODE_SHA256_AMD64}"; oc_arch="linux-x64" ;;
    arm64) oc_sha="${OPENCODE_SHA256_ARM64}"; oc_arch="linux-arm64" ;;
    *)
        echo "ERROR: no pinned OpenCode binary for '$(deb_arch)'" >&2
        exit 1
        ;;
esac

oc_tarball="cli-${oc_arch}-${OPENCODE_VERSION}.tgz"
oc_url="https://registry.npmjs.org/@opencode/cli-${oc_arch}/-/${oc_tarball}"

fetch_verified "${oc_url}" "${oc_sha}" "/tmp/${oc_tarball}"

mkdir -p "${PA_STAGE}/usr/local/bin"
tar -C "${PA_STAGE}/usr/local/bin" --strip-components=2 -xzf "/tmp/${oc_tarball}" "package/bin/opencode"
chmod 0755 "${PA_STAGE}/usr/local/bin/opencode"
rm -f "/tmp/${oc_tarball}"

"${PA_STAGE}/usr/local/bin/opencode" --version

mkdir -p "${PA_STAGE}/usr/local/share/pa-container/agents/opencode"
echo ".config/opencode/skills" > "${PA_STAGE}/usr/local/share/pa-container/agents/opencode/skills_path"

stage_record "opencode" "${OPENCODE_VERSION}"
