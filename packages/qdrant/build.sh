#!/bin/bash
# Build Qdrant vector database from source with SIMD acceleration and stage it.
#
# Run from ACP package builder, as root, at image build time.
set -euo pipefail
PA_STAGE="${PA_STAGE:-/out}"

require_env QDRANT_VERSION QDRANT_COMMIT

src="/usr/src/qdrant"
clone_verified "https://github.com/qdrant/qdrant.git" "${QDRANT_VERSION}" "${QDRANT_COMMIT}" "${src}"

cd "${src}"
cargo build --release --bin qdrant --no-default-features --features service
mkdir -p "${PA_STAGE}/usr/local/bin"
install -m755 target/release/qdrant "${PA_STAGE}/usr/local/bin/qdrant"
rm -rf "${src}" /root/.cargo/registry /root/.cargo/git

"${PA_STAGE}/usr/local/bin/qdrant" --version
stage_record "qdrant" "${QDRANT_VERSION}"

