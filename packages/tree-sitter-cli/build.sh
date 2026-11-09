#!/bin/bash
# Build tree-sitter CLI from source and stage it.
#
# Run from ACP package builder, as root, at image build time.
set -euo pipefail
PA_STAGE="${PA_STAGE:-/out}"

require_env TREE_SITTER_VERSION TREE_SITTER_COMMIT

src="/usr/src/tree-sitter"
clone_verified "https://github.com/tree-sitter/tree-sitter.git" "${TREE_SITTER_VERSION}" "${TREE_SITTER_COMMIT}" "${src}"

cd "${src}"
cargo build --release -p tree-sitter-cli
mkdir -p "${PA_STAGE}/usr/local/bin"
install -m755 target/release/tree-sitter "${PA_STAGE}/usr/local/bin/tree-sitter"
rm -rf "${src}" /root/.cargo/registry /root/.cargo/git

"${PA_STAGE}/usr/local/bin/tree-sitter" --version
stage_record "tree-sitter-cli" "${TREE_SITTER_VERSION}"

