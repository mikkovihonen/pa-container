#!/bin/bash
# Build gopls language server from source using the builder Go toolchain and stage it.
#
# Run from ACP package builder, as root, at image build time.
set -euo pipefail
PA_STAGE="${PA_STAGE:-/out}"

require_env GOPLS_VERSION GOPLS_COMMIT

src="/usr/src/tools"
clone_verified "https://github.com/golang/tools.git" "${GOPLS_VERSION}" "${GOPLS_COMMIT}" "${src}"

cd "${src}/gopls"
mkdir -p "${PA_STAGE}/usr/local/bin"
go build -o "${PA_STAGE}/usr/local/bin/gopls"
rm -rf "${src}" /root/go

"${PA_STAGE}/usr/local/bin/gopls" version
stage_record "gopls" "${GOPLS_VERSION}"

