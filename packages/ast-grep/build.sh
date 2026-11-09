#!/bin/bash
# Build ast-grep and sg from source and stage them.
#
# Run from ACP package builder, as root, at image build time.
set -euo pipefail
PA_STAGE="${PA_STAGE:-/out}"

require_env AST_GREP_VERSION AST_GREP_COMMIT

src="/usr/src/ast-grep"
clone_verified "https://github.com/ast-grep/ast-grep.git" "${AST_GREP_VERSION}" "${AST_GREP_COMMIT}" "${src}"

cd "${src}"
cargo build --release -p ast-grep
mkdir -p "${PA_STAGE}/usr/local/bin"
install -m755 target/release/ast-grep "${PA_STAGE}/usr/local/bin/ast-grep"
ln -sf ast-grep "${PA_STAGE}/usr/local/bin/sg"
rm -rf "${src}" /root/.cargo/registry /root/.cargo/git

"${PA_STAGE}/usr/local/bin/ast-grep" --version
stage_record "ast-grep" "${AST_GREP_VERSION}"

