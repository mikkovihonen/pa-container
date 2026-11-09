#!/bin/bash
set -euo pipefail
PA_STAGE="${PA_STAGE:-/out}"

ARCH="$(uname -m)"
case "${ARCH}" in
    x86_64) rust_sha="${RUST_SHA256_X86_64}" ;;
    aarch64) rust_sha="${RUST_SHA256_AARCH64}" ;;
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
