#!/bin/bash
# Staging recipe for data-tools capability: jq, yq, and miller (mlr)
set -euo pipefail
PA_STAGE="${PA_STAGE:-/out}"

mkdir -p "${PA_STAGE}/usr/local/bin" "${PA_STAGE}/usr/lib64"

install -m 0755 /usr/bin/jq "${PA_STAGE}/usr/local/bin/jq"
install -m 0755 /usr/bin/yq "${PA_STAGE}/usr/local/bin/yq"
install -m 0755 /usr/bin/mlr "${PA_STAGE}/usr/local/bin/mlr"

# Stage shared libraries for jq (libjq, oniguruma)
for bin in /usr/bin/jq; do
    for lib in $(ldd "${bin}" | awk '{print $3}' | grep -E '^/lib|^/usr/lib' || true); do
        case "$(basename "${lib}")" in
            libc.so*|ld-linux*|libdl.so*|libpthread.so*|librt.so*|libm.so*|libresolv.so*)
                ;;
            *)
                real_lib="$(realpath "${lib}")"
                cp -a "${lib}"* "${PA_STAGE}/usr/lib64/" 2>/dev/null || true
                cp -a "${real_lib}"* "${PA_STAGE}/usr/lib64/" 2>/dev/null || true
                ;;
        esac
    done
done

# Verification
"${PA_STAGE}/usr/local/bin/jq" --version
"${PA_STAGE}/usr/local/bin/yq" --version
"${PA_STAGE}/usr/local/bin/mlr" --version

echo "=== data-tools capability build complete ==="
