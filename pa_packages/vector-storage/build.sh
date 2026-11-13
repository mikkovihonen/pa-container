#!/bin/bash
# Staging recipe for vector-storage capability: sqlite-vec and USearch
set -euo pipefail
PA_STAGE="${PA_STAGE:-/out}"

require_env SQLITE_VEC_VERSION SQLITE_VEC_COMMIT USEARCH_VERSION

mkdir -p "${PA_STAGE}/usr/local/lib/sqlite" "${PA_STAGE}/usr/local/include" "${PA_STAGE}/usr/lib64"

# 1. Build sqlite-vec
src="$(mktemp -d)"
clone_verified "https://github.com/asg017/sqlite-vec.git" "${SQLITE_VEC_VERSION}" "${SQLITE_VEC_COMMIT}" "${src}"

cd "${src}"
ver="$(cat VERSION | tr -d ' \n\r')"
major="$(echo "${ver}" | cut -d. -f1)"
minor="$(echo "${ver}" | cut -d. -f2)"
patch="$(echo "${ver}" | cut -d. -f3 | cut -d- -f1)"

python3 -c "
import sys
tmpl = open('sqlite-vec.h.tmpl').read()
out = (
    tmpl.replace('\${VERSION}', '${ver}')
    .replace('\${VERSION_MAJOR}', '${major}')
    .replace('\${VERSION_MINOR}', '${minor}')
    .replace('\${VERSION_PATCH}', '${patch}')
    .replace('\${SOURCE}', '${SQLITE_VEC_COMMIT}')
    .replace('\${DATE}', '2024-01-01T00:00:00Z')
)
open('sqlite-vec.h', 'w').write(out)
"

arch="$(uname -m)"
simd_flags=""
if [ "${arch}" = "x86_64" ]; then
    simd_flags="-mavx -DSQLITE_VEC_ENABLE_AVX"
elif [ "${arch}" = "aarch64" ]; then
    simd_flags="-march=armv8-a+simd -DSQLITE_VEC_ENABLE_NEON -flax-vector-conversions"
fi

gcc -O3 -fPIC -shared -Wall -Wextra -Ivendor/ -I. -lm ${simd_flags} sqlite-vec.c -o vec0.so
install -m755 vec0.so "${PA_STAGE}/usr/local/lib/sqlite/vec0.so"
install -m644 sqlite-vec.h "${PA_STAGE}/usr/local/include/sqlite-vec.h"
rm -rf "${src}"

# 2. Stage USearch
case "${arch}" in
    x86_64)
        usearch_sqlite_sha="${USEARCH_SQLITE_SHA256_X86_64}"
        usearch_lib_sha="${USEARCH_LIB_SHA256_X86_64}"
        usearch_sqlite_url="https://github.com/unum-cloud/usearch/releases/download/v${USEARCH_VERSION}/usearch_sqlite_linux_amd64_${USEARCH_VERSION}.so"
        usearch_lib_url="https://github.com/unum-cloud/usearch/releases/download/v${USEARCH_VERSION}/usearch_linux_amd64_${USEARCH_VERSION}.so"
        ;;
    aarch64)
        usearch_sqlite_sha="${USEARCH_SQLITE_SHA256_AARCH64}"
        usearch_lib_sha="${USEARCH_LIB_SHA256_AARCH64}"
        usearch_sqlite_url="https://github.com/unum-cloud/usearch/releases/download/v${USEARCH_VERSION}/usearch_sqlite_linux_arm64_${USEARCH_VERSION}.so"
        usearch_lib_url="https://github.com/unum-cloud/usearch/releases/download/v${USEARCH_VERSION}/usearch_linux_arm64_${USEARCH_VERSION}.so"
        ;;
    *)
        echo "Unsupported architecture: ${arch}" >&2
        exit 1
        ;;
esac

fetch_verified "${usearch_sqlite_url}" "${usearch_sqlite_sha}" "${PA_STAGE}/usr/local/lib/sqlite/usearch_sqlite.so"
fetch_verified "${usearch_lib_url}" "${usearch_lib_sha}" "${PA_STAGE}/usr/local/lib/libusearch.so"
chmod 0755 "${PA_STAGE}/usr/local/lib/sqlite/usearch_sqlite.so" "${PA_STAGE}/usr/local/lib/libusearch.so"

# Ensure libsqlite3.so symlink exists in lib64 for usearch dynamic loader
ln -sf libsqlite3.so.0 "${PA_STAGE}/usr/lib64/libsqlite3.so"

# 3. Verification in build environment
echo "Verifying vector extensions in SQLite..."
ln -sf /usr/lib64/libsqlite3.so.0 /usr/lib64/libsqlite3.so 2>/dev/null || true
sqlite3 :memory: ".load ${PA_STAGE}/usr/local/lib/sqlite/vec0" "SELECT vec_version();"
sqlite3 :memory: ".load ${PA_STAGE}/usr/local/lib/sqlite/usearch_sqlite" "SELECT distance_hamming_unicode('test', 'text');"

echo "=== vector-storage capability build complete ==="
