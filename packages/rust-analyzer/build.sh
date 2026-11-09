#!/bin/bash
# Build rust-analyzer from source using the builder Rust toolchain and stage it.
#
# Run from coding-agent-builder/Containerfile, as root, at image build time.
set -euo pipefail
PA_STAGE="${PA_STAGE:-/out}"
# legacy path
# legacy check
# shellcheck source=/dev/null
# common sourced

require_env RUST_ANALYZER_VERSION RUST_ANALYZER_COMMIT

src="/usr/src/rust-analyzer"
clone_verified "https://github.com/rust-lang/rust-analyzer.git" "${RUST_ANALYZER_VERSION}" "${RUST_ANALYZER_COMMIT}" "${src}"

cd "${src}"
cargo build --release -p rust-analyzer
mkdir -p "${PA_STAGE}/usr/local/bin"
install -m755 target/release/rust-analyzer "${PA_STAGE}/usr/local/bin/rust-analyzer"
rm -rf "${src}" /root/.cargo/registry /root/.cargo/git

"${PA_STAGE}/usr/local/bin/rust-analyzer" --version
stage_record "rust-analyzer" "${RUST_ANALYZER_VERSION}"

