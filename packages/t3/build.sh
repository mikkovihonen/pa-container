#!/bin/bash
set -euo pipefail
PA_STAGE="${PA_STAGE:-/out}"

ARCH="$(uname -m)"
case "${ARCH}" in
    x86_64)
        t3_sha="${T3_SHA256_AMD64}"
        t3_arch="x64"
        ;;
    aarch64)
        t3_sha="${T3_SHA256_ARM64}"
        t3_arch="arm64"
        ;;
    *)
        echo "ERROR: Unsupported architecture ${ARCH}" >&2
        exit 1
        ;;
esac

t3_tarball="t3-${T3_VERSION}-linux-${t3_arch}.tar.gz"
t3_url="https://github.com/pingdotgg/t3code/releases/download/v${T3_VERSION}/${t3_tarball}"

curl -fsSL -o "/tmp/${t3_tarball}" "${t3_url}"
echo "${t3_sha}  /tmp/${t3_tarball}" | sha256sum -c -

mkdir -p "${PA_STAGE}/usr/local/lib/t3"
tar -C "${PA_STAGE}/usr/local/lib/t3" --strip-components=1 -xzf "/tmp/${t3_tarball}"
rm -f "/tmp/${t3_tarball}"

mkdir -p "${PA_STAGE}/usr/local/bin"
ln -sf ../lib/t3/t3 "${PA_STAGE}/usr/local/bin/t3"
