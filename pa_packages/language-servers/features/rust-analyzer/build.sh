#!/bin/bash
# Install and stage rust-analyzer
set -euo pipefail
PA_STAGE="${PA_STAGE:-/out}"

require_env RUST_ANALYZER_VERSION RUST_ANALYZER_SHA256_X86_64 RUST_ANALYZER_SHA256_AARCH64

arch="$(uname -m)"
case "${arch}" in
    x86_64)
        bin_file="rust-analyzer-x86_64-unknown-linux-gnu.gz"
        expected_sha="${RUST_ANALYZER_SHA256_X86_64}"
        ;;
    aarch64|arm64)
        bin_file="rust-analyzer-aarch64-unknown-linux-gnu.gz"
        expected_sha="${RUST_ANALYZER_SHA256_AARCH64}"
        ;;
    *)
        echo "Unsupported architecture: ${arch}" >&2
        exit 1
        ;;
esac

url="https://github.com/rust-lang/rust-analyzer/releases/download/${RUST_ANALYZER_VERSION}/${bin_file}"
fetch_verified "${url}" "${expected_sha}" "/tmp/${bin_file}"

mkdir -p "${PA_STAGE}/usr/local/bin"
gzip -dc "/tmp/${bin_file}" > "${PA_STAGE}/usr/local/bin/rust-analyzer"
chmod 0755 "${PA_STAGE}/usr/local/bin/rust-analyzer"
rm -f "/tmp/${bin_file}"

"${PA_STAGE}/usr/local/bin/rust-analyzer" --version
stage_record "rust-analyzer" "${RUST_ANALYZER_VERSION}"
