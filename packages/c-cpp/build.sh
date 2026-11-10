#!/bin/bash
# Staging recipe for C/C++ capability:
# clangd, mold, cmake, ninja
set -euo pipefail
PA_STAGE="${PA_STAGE:-/out}"
mkdir -p "${PA_STAGE}/usr/local/bin" "${PA_STAGE}/usr/local/lib"

ARCH="$(uname -m)"
case "${ARCH}" in
    x86_64)
        mold_sha="${MOLD_SHA256_X86_64}"
        cmake_sha="${CMAKE_SHA256_X86_64}"
        cmake_arch="x86_64"
        ;;
    aarch64)
        mold_sha="${MOLD_SHA256_AARCH64}"
        cmake_sha="${CMAKE_SHA256_AARCH64}"
        cmake_arch="aarch64"
        ;;
    *)
        echo "ERROR: Unsupported architecture ${ARCH}" >&2
        exit 1
        ;;
esac

echo "=== Staging clangd and ninja ==="
install -m 0755 /usr/bin/clangd "${PA_STAGE}/usr/local/bin/clangd"
install -m 0755 /usr/bin/ninja "${PA_STAGE}/usr/local/bin/ninja"

mkdir -p "${PA_STAGE}/usr/lib64"
for bin in /usr/bin/clangd /usr/bin/ninja; do
    for lib in $(ldd "${bin}" | awk '{print $3}' | grep -E '^/lib|^/usr/lib' || true); do
        case "$(basename "${lib}")" in
            libc.so*|ld-linux*|libdl.so*|libpthread.so*|librt.so*)
                ;;
            *)
                real_lib="$(realpath "${lib}")"
                cp -a "${lib}"* "${PA_STAGE}/usr/lib64/" 2>/dev/null || true
                cp -a "${real_lib}"* "${PA_STAGE}/usr/lib64/" 2>/dev/null || true
                ;;
        esac
    done
done

# Copy clang headers / resources if present
if [ -d /usr/lib64/clang ]; then
    cp -a /usr/lib64/clang "${PA_STAGE}/usr/lib64/"
elif [ -d /usr/lib/clang ]; then
    mkdir -p "${PA_STAGE}/usr/lib"
    cp -a /usr/lib/clang "${PA_STAGE}/usr/lib/"
fi

echo "=== Installing CMake ${CMAKE_VERSION} ==="
cmake_tarball="cmake-${CMAKE_VERSION}-linux-${cmake_arch}.tar.gz"
fetch_verified "https://github.com/Kitware/CMake/releases/download/v${CMAKE_VERSION}/${cmake_tarball}" "${cmake_sha}" "/tmp/${cmake_tarball}"
tar -C "${PA_STAGE}/usr/local" --strip-components=1 -xzf "/tmp/${cmake_tarball}"
rm -f "/tmp/${cmake_tarball}"

echo "=== Installing mold ${MOLD_VERSION} ==="
mold_tarball="mold-${MOLD_VERSION}-${ARCH}-linux.tar.gz"
fetch_verified "https://github.com/rui314/mold/releases/download/v${MOLD_VERSION}/${mold_tarball}" "${mold_sha}" "/tmp/${mold_tarball}"
mkdir -p /tmp/mold
tar -C /tmp/mold --strip-components=1 -xzf "/tmp/${mold_tarball}"
install -m 0755 /tmp/mold/bin/mold "${PA_STAGE}/usr/local/bin/mold"
ln -sf mold "${PA_STAGE}/usr/local/bin/ld.mold"
rm -rf /tmp/mold "/tmp/${mold_tarball}"

# Verification
"${PA_STAGE}/usr/local/bin/clangd" --version
"${PA_STAGE}/usr/local/bin/mold" --version
"${PA_STAGE}/usr/local/bin/cmake" --version
"${PA_STAGE}/usr/local/bin/ninja" --version

echo "=== C/C++ capability build complete ==="
