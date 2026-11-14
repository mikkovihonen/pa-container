#!/bin/bash
set -euo pipefail
PA_STAGE="${PA_STAGE:-/out}"

ARCH="$(uname -m)"
case "${ARCH}" in
    x86_64)
        rust_sha="${RUST_SHA256_X86_64}"
        ra_sha="${RUST_ANALYZER_SHA256_X86_64}"
        ;;
    aarch64)
        rust_sha="${RUST_SHA256_AARCH64}"
        ra_sha="${RUST_ANALYZER_SHA256_AARCH64}"
        ;;
    *)
        echo "ERROR: Unsupported architecture ${ARCH}" >&2
        exit 1
        ;;
esac

rust_pkg="rust-${RUST_VERSION}-${ARCH}-unknown-linux-gnu"
curl -fsSL -o "/tmp/${rust_pkg}.tar.gz" "https://static.rust-lang.org/dist/${RUST_DIST_DATE}/${rust_pkg}.tar.gz"
echo "${rust_sha}  /tmp/${rust_pkg}.tar.gz" | sha256sum -c -

tar -C /tmp -xzf "/tmp/${rust_pkg}.tar.gz"
mkdir -p "${PA_STAGE}/usr/local"
"/tmp/${rust_pkg}/install.sh" --prefix="${PA_STAGE}/usr/local" --without=rust-docs --disable-ldconfig
rm -rf "/tmp/${rust_pkg}" "/tmp/${rust_pkg}.tar.gz"

# Install rust-analyzer
echo "=== Installing rust-analyzer ${RUST_ANALYZER_VERSION} ==="
ra_url="https://github.com/rust-lang/rust-analyzer/releases/download/${RUST_ANALYZER_VERSION}/rust-analyzer-${ARCH}-unknown-linux-gnu.gz"
fetch_verified "${ra_url}" "${ra_sha}" "/tmp/rust-analyzer.gz"
gzip -d -c "/tmp/rust-analyzer.gz" > "${PA_STAGE}/usr/local/bin/rust-analyzer"
chmod 0755 "${PA_STAGE}/usr/local/bin/rust-analyzer"
rm -f "/tmp/rust-analyzer.gz"

# Verification
"${PA_STAGE}/usr/local/bin/rustc" --version
"${PA_STAGE}/usr/local/bin/cargo" --version
"${PA_STAGE}/usr/local/bin/rust-analyzer" --version

echo "=== Rust capability build complete ==="
