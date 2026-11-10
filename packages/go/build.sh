#!/bin/bash
# Staging recipe for Go toolchain and gopls language server
set -euo pipefail
PA_STAGE="${PA_STAGE:-/out}"

case "$(deb_arch)" in
    amd64)
        go_arch="linux-amd64"
        go_sha="${GO_SHA256_AMD64}"
        ;;
    arm64)
        go_arch="linux-arm64"
        go_sha="${GO_SHA256_ARM64}"
        ;;
    *)
        echo "ERROR: Unsupported architecture $(deb_arch)" >&2
        exit 1
        ;;
esac

echo "=== Downloading Go ${GO_VERSION} ==="
fetch_verified "https://go.dev/dl/go${GO_VERSION}.${go_arch}.tar.gz" "${go_sha}" "/tmp/go.tar.gz"
mkdir -p "${PA_STAGE}/usr/local"
tar -C "${PA_STAGE}/usr/local" -xzf "/tmp/go.tar.gz"
rm -f "/tmp/go.tar.gz"

# Link Go for build stage and set PATH
mkdir -p /usr/local
ln -sf "${PA_STAGE}/usr/local/go" /usr/local/go
export PATH="/usr/local/go/bin:${PATH}"

# Staged symlinks for consumer containers
mkdir -p "${PA_STAGE}/usr/local/bin"
ln -sf ../go/bin/go "${PA_STAGE}/usr/local/bin/go"
ln -sf ../go/bin/gofmt "${PA_STAGE}/usr/local/bin/gofmt"

echo "=== Building gopls ${GOPLS_VERSION} ==="
src="/usr/src/tools"
clone_verified "https://github.com/golang/tools.git" "${GOPLS_VERSION}" "${GOPLS_COMMIT}" "${src}"

cd "${src}/gopls"
go build -o "${PA_STAGE}/usr/local/bin/gopls"

cd /
rm -rf "${src}" /root/go /root/.cache

# Verification
"${PA_STAGE}/usr/local/bin/go" version
"${PA_STAGE}/usr/local/bin/gopls" version

echo "=== Go capability build complete ==="
