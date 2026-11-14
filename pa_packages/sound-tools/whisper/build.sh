#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_ROOT="${PA_STAGE:-${STAGE_DIR:-}}"

MODEL_NAME="ggml-base-q5_1.bin"
MODEL_URL="https://huggingface.co/ggerganov/whisper.cpp/resolve/main/${MODEL_NAME}"
MODEL_SHA256="422f1ae452ade6f30a004d7e5c6a43195e4433bc370bf23fac9cc591f01a8898"

if [ "$(id -u)" = "0" ] && command -v microdnf >/dev/null 2>&1; then
    microdnf install -y \
        gcc \
        pkgconf-pkg-config \
        whisper-cpp-devel \
        libsndfile-devel \
        curl \
        ca-certificates || true
fi

mkdir -p "${TARGET_ROOT}/usr/local/bin" "${TARGET_ROOT}/usr/local/share/whisper"

CFLAGS="$(pkg-config --cflags whisper sndfile 2>/dev/null || true)"
LIBS="$(pkg-config --libs whisper sndfile 2>/dev/null || echo '-lwhisper -lsndfile')"

# shellcheck disable=SC2086
gcc -O2 -Wall -Wextra \
    "${SCRIPT_DIR}/whisper-cli.c" \
    ${CFLAGS} ${LIBS} \
    -o "${TARGET_ROOT}/usr/local/bin/whisper-cli"

chmod 0755 "${TARGET_ROOT}/usr/local/bin/whisper-cli"

# Verify dynamic linking against Fedora shared libraries
ldd "${TARGET_ROOT}/usr/local/bin/whisper-cli" | grep -q "libwhisper.so"
ldd "${TARGET_ROOT}/usr/local/bin/whisper-cli" | grep -q "libsndfile.so"

MODEL_DEST="${TARGET_ROOT}/usr/local/share/whisper/${MODEL_NAME}"
curl -fsSL --retry 3 -o "${MODEL_DEST}" "${MODEL_URL}"
echo "${MODEL_SHA256}  ${MODEL_DEST}" | sha256sum -c -
chmod 0644 "${MODEL_DEST}"
ln -sf "${MODEL_NAME}" "${TARGET_ROOT}/usr/local/share/whisper/ggml-base.bin"
