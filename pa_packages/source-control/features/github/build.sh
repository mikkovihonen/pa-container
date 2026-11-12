#!/bin/bash
# Download, verify, and stage the GitHub CLI (gh) release archive.
#
# Run from ACP package builder, as root, at image build time.
set -euo pipefail
PA_STAGE="${PA_STAGE:-/out}"

require_env GH_VERSION GH_SHA256_AMD64 GH_SHA256_ARM64

case "$(deb_arch)" in
    amd64) gh_sha="${GH_SHA256_AMD64}"; gh_arch="amd64" ;;
    arm64) gh_sha="${GH_SHA256_ARM64}"; gh_arch="arm64" ;;
    *)
        echo "ERROR: no pinned GitHub CLI archive for '$(deb_arch)'" >&2
        exit 1
        ;;
esac

gh_tarball="gh_${GH_VERSION}_linux_${gh_arch}.tar.gz"
gh_url="https://github.com/cli/cli/releases/download/v${GH_VERSION}/${gh_tarball}"

fetch_verified "${gh_url}" "${gh_sha}" "/tmp/${gh_tarball}"

mkdir -p "${PA_STAGE}/usr/local/bin"
tar -C "${PA_STAGE}/usr/local/bin" --strip-components=2 -xzf "/tmp/${gh_tarball}" "gh_${GH_VERSION}_linux_${gh_arch}/bin/gh"
chmod 0755 "${PA_STAGE}/usr/local/bin/gh"
rm -f "/tmp/${gh_tarball}"

"${PA_STAGE}/usr/local/bin/gh" --version
stage_record "gh" "${GH_VERSION}"
