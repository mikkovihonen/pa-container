#!/bin/bash
# Install and stage clangd
set -euo pipefail
PA_STAGE="${PA_STAGE:-/out}"

mkdir -p "${PA_STAGE}/usr/local/bin" "${PA_STAGE}/usr/lib64"

echo "=== Staging clangd ==="
install -m 0755 /usr/bin/clangd "${PA_STAGE}/usr/local/bin/clangd"

for bin in /usr/bin/clangd; do
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

"${PA_STAGE}/usr/local/bin/clangd" --version
stage_record "clangd" "system"
