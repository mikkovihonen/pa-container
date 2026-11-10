#!/bin/bash
# Staging recipe for developer-tools capability: just task runner
set -euo pipefail
PA_STAGE="${PA_STAGE:-/out}"

mkdir -p "${PA_STAGE}/usr/local/bin"

ARCH="$(uname -m)"
case "${ARCH}" in
    x86_64)
        JUST_ARCH="x86_64-unknown-linux-musl"
        EXPECTED_SHA="${JUST_SHA256_X86_64}"
        ;;
    aarch64|arm64)
        JUST_ARCH="aarch64-unknown-linux-musl"
        EXPECTED_SHA="${JUST_SHA256_AARCH64}"
        ;;
    *)
        echo "Unsupported architecture: ${ARCH}" >&2
        exit 1
        ;;
esac

JUST_URL="https://github.com/casey/just/releases/download/${JUST_VERSION}/just-${JUST_VERSION}-${JUST_ARCH}.tar.gz"
tmp_just="$(mktemp -d)"
echo "Downloading just ${JUST_VERSION} for ${JUST_ARCH}..."
curl -fsSL -o "${tmp_just}/just.tar.gz" "${JUST_URL}"

echo "${EXPECTED_SHA}  ${tmp_just}/just.tar.gz" | sha256sum -c -
mkdir -p "${tmp_just}/extracted"
tar -xzf "${tmp_just}/just.tar.gz" -C "${tmp_just}/extracted"
install -m 0755 "${tmp_just}/extracted/just" "${PA_STAGE}/usr/local/bin/just"
rm -rf "${tmp_just}"

# Verification
"${PA_STAGE}/usr/local/bin/just" --version

echo "=== developer-tools capability build complete ==="
