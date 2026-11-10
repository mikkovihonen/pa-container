#!/bin/bash
# Staging recipe for Zig toolchain and zls language server
set -euo pipefail
PA_STAGE="${PA_STAGE:-/out}"
mkdir -p "${PA_STAGE}/usr/local/bin" "${PA_STAGE}/usr/local/lib"

ARCH="$(uname -m)"
case "${ARCH}" in
    x86_64)
        zig_arch="x86_64"
        zig_sha="${ZIG_SHA256_X86_64}"
        zls_arch="x86_64"
        zls_sha="${ZLS_SHA256_X86_64}"
        ;;
    aarch64)
        zig_arch="aarch64"
        zig_sha="${ZIG_SHA256_AARCH64}"
        zls_arch="aarch64"
        zls_sha="${ZLS_SHA256_AARCH64}"
        ;;
    *)
        echo "ERROR: Unsupported architecture ${ARCH}" >&2
        exit 1
        ;;
esac

echo "=== Downloading Zig ${ZIG_VERSION} ==="
zig_tarball="zig-${zig_arch}-linux-${ZIG_VERSION}.tar.xz"
fetch_verified "https://ziglang.org/download/${ZIG_VERSION}/${zig_tarball}" "${zig_sha}" "/tmp/${zig_tarball}"
mkdir -p /tmp/zig
tar -C /tmp/zig --strip-components=1 -xJf "/tmp/${zig_tarball}"
install -m 0755 /tmp/zig/zig "${PA_STAGE}/usr/local/bin/zig"
cp -a /tmp/zig/lib "${PA_STAGE}/usr/local/lib/zig"
rm -rf /tmp/zig "/tmp/${zig_tarball}"

echo "=== Downloading zls ${ZLS_VERSION} ==="
zls_tarball="zls-${zls_arch}-linux.tar.xz"
fetch_verified "https://github.com/zigtools/zls/releases/download/${ZLS_VERSION}/${zls_tarball}" "${zls_sha}" "/tmp/${zls_tarball}"
tar -C /tmp -xJf "/tmp/${zls_tarball}"
install -m 0755 /tmp/zls "${PA_STAGE}/usr/local/bin/zls"
rm -rf /tmp/zls "/tmp/${zls_tarball}"

# Verification
"${PA_STAGE}/usr/local/bin/zig" version
"${PA_STAGE}/usr/local/bin/zls" --version

echo "=== Zig capability build complete ==="
