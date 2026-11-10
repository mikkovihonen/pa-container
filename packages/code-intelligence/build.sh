#!/bin/bash
# Staging recipe for code-intelligence capability:
# ripgrep, fd, ast-grep, tree-sitter, colgrep, repomix, tokencount
set -euo pipefail

PA_STAGE="${PA_STAGE:-/out}"
mkdir -p "${PA_STAGE}/usr/local/bin"

ARCH="$(uname -m)"
case "${ARCH}" in
    x86_64)
        rg_url="https://github.com/BurntSushi/ripgrep/releases/download/${RIPGREP_VERSION}/ripgrep-${RIPGREP_VERSION}-x86_64-unknown-linux-musl.tar.gz"
        rg_sha="${RIPGREP_SHA256_X86_64}"
        fd_url="https://github.com/sharkdp/fd/releases/download/${FD_VERSION}/fd-${FD_VERSION}-x86_64-unknown-linux-musl.tar.gz"
        fd_sha="${FD_SHA256_X86_64}"
        ast_url="https://github.com/ast-grep/ast-grep/releases/download/${AST_GREP_VERSION}/app-x86_64-unknown-linux-gnu.zip"
        ast_sha="${AST_GREP_SHA256_X86_64}"
        ts_url="https://github.com/tree-sitter/tree-sitter/releases/download/${TREE_SITTER_VERSION}/tree-sitter-linux-x64.gz"
        ts_sha="${TREE_SITTER_SHA256_X86_64}"
        ;;
    aarch64)
        rg_url="https://github.com/BurntSushi/ripgrep/releases/download/${RIPGREP_VERSION}/ripgrep-${RIPGREP_VERSION}-aarch64-unknown-linux-gnu.tar.gz"
        rg_sha="${RIPGREP_SHA256_AARCH64}"
        fd_url="https://github.com/sharkdp/fd/releases/download/${FD_VERSION}/fd-${FD_VERSION}-aarch64-unknown-linux-gnu.tar.gz"
        fd_sha="${FD_SHA256_AARCH64}"
        ast_url="https://github.com/ast-grep/ast-grep/releases/download/${AST_GREP_VERSION}/app-aarch64-unknown-linux-gnu.zip"
        ast_sha="${AST_GREP_SHA256_AARCH64}"
        ts_url="https://github.com/tree-sitter/tree-sitter/releases/download/${TREE_SITTER_VERSION}/tree-sitter-linux-arm64.gz"
        ts_sha="${TREE_SITTER_SHA256_AARCH64}"
        ;;
    *)
        echo "ERROR: Unsupported architecture ${ARCH}" >&2
        exit 1
        ;;
esac

# 1. ripgrep
echo "=== Installing ripgrep ${RIPGREP_VERSION} ==="
fetch_verified "${rg_url}" "${rg_sha}" "/tmp/rg.tar.gz"
tar -C /tmp -xzf "/tmp/rg.tar.gz"
install -m 0755 /tmp/ripgrep-*/rg "${PA_STAGE}/usr/local/bin/rg"
rm -rf /tmp/rg.tar.gz /tmp/ripgrep-*

# 2. fd
echo "=== Installing fd ${FD_VERSION} ==="
fetch_verified "${fd_url}" "${fd_sha}" "/tmp/fd.tar.gz"
tar -C /tmp -xzf "/tmp/fd.tar.gz"
install -m 0755 /tmp/fd-*/fd "${PA_STAGE}/usr/local/bin/fd"
rm -rf /tmp/fd.tar.gz /tmp/fd-*

# 3. ast-grep
echo "=== Installing ast-grep ${AST_GREP_VERSION} ==="
fetch_verified "${ast_url}" "${ast_sha}" "/tmp/ast-grep.zip"
unzip -q -o "/tmp/ast-grep.zip" -d /tmp/ast-grep
install -m 0755 /tmp/ast-grep/ast-grep "${PA_STAGE}/usr/local/bin/ast-grep"
ln -sf ast-grep "${PA_STAGE}/usr/local/bin/sg"
rm -rf /tmp/ast-grep.zip /tmp/ast-grep

# 4. tree-sitter
echo "=== Installing tree-sitter ${TREE_SITTER_VERSION} ==="
fetch_verified "${ts_url}" "${ts_sha}" "/tmp/tree-sitter.gz"
gzip -d -c "/tmp/tree-sitter.gz" > "${PA_STAGE}/usr/local/bin/tree-sitter"
chmod 0755 "${PA_STAGE}/usr/local/bin/tree-sitter"
rm -f "/tmp/tree-sitter.gz"

# 5. colgrep
echo "=== Building colgrep ==="
src="/usr/src/colgrep"
git -c advice.detachedHead=false clone --quiet --depth 1 "https://github.com/lightonai/next-plaid.git" "${src}"
head="$(git -C "${src}" rev-parse HEAD)"
if [ "${head}" != "${COLGREP_COMMIT}" ]; then
    echo "ERROR: colgrep commit ${head} does not match expected ${COLGREP_COMMIT}" >&2
    exit 1
fi
cargo build --manifest-path "${src}/Cargo.toml" --release -p colgrep
install -m 0755 "${src}/target/release/colgrep" "${PA_STAGE}/usr/local/bin/colgrep"
rm -rf "${src}" /root/.cargo/registry /root/.cargo/git

# 6. repomix (via npm)
echo "=== Installing repomix ${REPOMIX_VERSION} ==="
npm install -g --prefix="${PA_STAGE}/usr/local" "repomix@${REPOMIX_VERSION}"

# 7. tokencount wrapper
cat << 'EOF' > "${PA_STAGE}/usr/local/bin/tokencount"
#!/usr/bin/env bash
# Quick token counting wrapper using repomix
set -euo pipefail
exec repomix --token-count-encoding o200k_base "$@"
EOF
chmod 0755 "${PA_STAGE}/usr/local/bin/tokencount"

# Verification in build stage
"${PA_STAGE}/usr/local/bin/rg" --version
"${PA_STAGE}/usr/local/bin/fd" --version
"${PA_STAGE}/usr/local/bin/ast-grep" --version
"${PA_STAGE}/usr/local/bin/sg" --version
"${PA_STAGE}/usr/local/bin/tree-sitter" --version
"${PA_STAGE}/usr/local/bin/colgrep" --version
PATH="${PA_STAGE}/usr/local/bin:${PATH}" "${PA_STAGE}/usr/local/bin/repomix" --version
PATH="${PA_STAGE}/usr/local/bin:${PATH}" "${PA_STAGE}/usr/local/bin/tokencount" --help

echo "=== code-intelligence capability build complete ==="
