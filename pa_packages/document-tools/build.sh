#!/bin/bash
# Staging recipe for document-tools capability: Pandoc and Poppler utilities
set -euo pipefail
PA_STAGE="${PA_STAGE:-/out}"

mkdir -p "${PA_STAGE}/usr/local/bin" "${PA_STAGE}/usr/lib64"

# 1. Install Pandoc
ARCH="$(uname -m)"
case "${ARCH}" in
    x86_64)
        PANDOC_ARCH="x86_64"
        EXPECTED_SHA="${PANDOC_SHA256_X86_64}"
        ;;
    aarch64|arm64)
        PANDOC_ARCH="arm64"
        EXPECTED_SHA="${PANDOC_SHA256_AARCH64}"
        ;;
    *)
        echo "Unsupported architecture: ${ARCH}" >&2
        exit 1
        ;;
esac

PANDOC_URL="https://github.com/jgm/pandoc/releases/download/${PANDOC_VERSION}/pandoc-${PANDOC_VERSION}-linux-${PANDOC_ARCH}.tar.gz"
tmp_pandoc="$(mktemp -d)"
echo "Downloading Pandoc ${PANDOC_VERSION} for ${PANDOC_ARCH}..."
curl -fsSL -o "${tmp_pandoc}/pandoc.tar.gz" "${PANDOC_URL}"

echo "${EXPECTED_SHA}  ${tmp_pandoc}/pandoc.tar.gz" | sha256sum -c -
mkdir -p "${tmp_pandoc}/extracted"
tar -xzf "${tmp_pandoc}/pandoc.tar.gz" -C "${tmp_pandoc}/extracted" --strip-components=1
install -m 0755 "${tmp_pandoc}/extracted/bin/pandoc" "${PA_STAGE}/usr/local/bin/pandoc"
rm -rf "${tmp_pandoc}"

# 2. Stage Poppler utilities (pdftotext, pdfinfo, pdftoppm, etc.)
echo "Staging Poppler utilities..."
for bin in /usr/bin/pdf*; do
    [ -f "${bin}" ] || continue
    install -m 0755 "${bin}" "${PA_STAGE}/usr/local/bin/$(basename "${bin}")"
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

# Copy poppler data (CMap files) if present
if [ -d /usr/share/poppler ]; then
    mkdir -p "${PA_STAGE}/usr/share"
    cp -a /usr/share/poppler "${PA_STAGE}/usr/share/"
fi

# 3. Verification
echo "Verifying document-tools in staging..."
"${PA_STAGE}/usr/local/bin/pandoc" --version | head -n 2
LD_LIBRARY_PATH="${PA_STAGE}/usr/lib64:${LD_LIBRARY_PATH:-}" "${PA_STAGE}/usr/local/bin/pdftotext" -v
LD_LIBRARY_PATH="${PA_STAGE}/usr/lib64:${LD_LIBRARY_PATH:-}" "${PA_STAGE}/usr/local/bin/pdfinfo" -v

echo "=== document-tools capability build complete ==="
