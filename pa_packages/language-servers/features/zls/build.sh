#!/bin/bash
# Install and stage zls
set -euo pipefail
PA_STAGE="${PA_STAGE:-/out}"

require_env ZLS_VERSION ZLS_SHA256_X86_64 ZLS_SHA256_AARCH64

ARCH="$(uname -m)"
case "${ARCH}" in
    x86_64)
        zls_arch="x86_64"
        zls_sha="${ZLS_SHA256_X86_64}"
        ;;
    aarch64|arm64)
        zls_arch="aarch64"
        zls_sha="${ZLS_SHA256_AARCH64}"
        ;;
    *)
        echo "ERROR: Unsupported architecture ${ARCH}" >&2
        exit 1
        ;;
esac

echo "=== Downloading zls ${ZLS_VERSION} ==="
zls_tarball="zls-${zls_arch}-linux.tar.xz"
fetch_verified "https://github.com/zigtools/zls/releases/download/${ZLS_VERSION}/${zls_tarball}" "${zls_sha}" "/tmp/${zls_tarball}"
mkdir -p "${PA_STAGE}/usr/local/bin"
tar -C /tmp -xJf "/tmp/${zls_tarball}"
install -m 0755 /tmp/zls "${PA_STAGE}/usr/local/bin/zls"
rm -rf /tmp/zls "/tmp/${zls_tarball}"

"${PA_STAGE}/usr/local/bin/zls" --version
stage_record "zls" "${ZLS_VERSION}"
