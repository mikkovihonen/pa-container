#!/bin/bash
# Install and stage Qdrant vector database pre-built static binary.
set -euo pipefail
PA_STAGE="${PA_STAGE:-/out}"

require_env QDRANT_VERSION QDRANT_SHA256_AMD64 QDRANT_SHA256_ARM64

arch="$(uname -m)"
case "${arch}" in
    x86_64)
        tarball="qdrant-x86_64-unknown-linux-musl.tar.gz"
        expected_sha="${QDRANT_SHA256_AMD64}"
        ;;
    aarch64|arm64)
        tarball="qdrant-aarch64-unknown-linux-musl.tar.gz"
        expected_sha="${QDRANT_SHA256_ARM64}"
        ;;
    *)
        echo "Unsupported architecture: ${arch}" >&2
        exit 1
        ;;
esac

url="https://github.com/qdrant/qdrant/releases/download/v${QDRANT_VERSION}/${tarball}"
fetch_verified "${url}" "${expected_sha}" "/tmp/${tarball}"

mkdir -p "${PA_STAGE}/usr/local/bin"
tar -xzf "/tmp/${tarball}" -C "${PA_STAGE}/usr/local/bin" qdrant
chmod 0755 "${PA_STAGE}/usr/local/bin/qdrant"
rm -f "/tmp/${tarball}"

"${PA_STAGE}/usr/local/bin/qdrant" --version
stage_record "qdrant" "${QDRANT_VERSION}"
