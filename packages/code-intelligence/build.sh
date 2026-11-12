#!/bin/bash
# Staging recipe for code-intelligence capability:
# ast-grep, colgrep, repomix, tokencount
# (ripgrep, fd, and tree-sitter are installed via distro_package)
set -euo pipefail

PA_STAGE="${PA_STAGE:-/out}"
mkdir -p "${PA_STAGE}/usr/local/bin"

ARCH="$(uname -m)"
case "${ARCH}" in
    x86_64)
        ast_url="https://github.com/ast-grep/ast-grep/releases/download/${AST_GREP_VERSION}/app-x86_64-unknown-linux-gnu.zip"
        ast_sha="${AST_GREP_SHA256_X86_64}"
        ;;
    aarch64)
        ast_url="https://github.com/ast-grep/ast-grep/releases/download/${AST_GREP_VERSION}/app-aarch64-unknown-linux-gnu.zip"
        ast_sha="${AST_GREP_SHA256_AARCH64}"
        ;;
    *)
        echo "ERROR: Unsupported architecture ${ARCH}" >&2
        exit 1
        ;;
esac

# 1. ast-grep
echo "=== Installing ast-grep ${AST_GREP_VERSION} ==="
fetch_verified "${ast_url}" "${ast_sha}" "/tmp/ast-grep.zip"
unzip -q -o "/tmp/ast-grep.zip" -d /tmp/ast-grep
install -m 0755 /tmp/ast-grep/ast-grep "${PA_STAGE}/usr/local/bin/ast-grep"
ln -sf ast-grep "${PA_STAGE}/usr/local/bin/sg"
rm -rf /tmp/ast-grep.zip /tmp/ast-grep

# 2. colgrep
echo "=== Building colgrep ==="
src="$(mktemp -d)"
git -c advice.detachedHead=false clone --quiet --depth 1 "https://github.com/lightonai/next-plaid.git" "${src}"
head="$(git -C "${src}" rev-parse HEAD)"
if [ "${head}" != "${COLGREP_COMMIT}" ]; then
    echo "ERROR: colgrep commit ${head} does not match expected ${COLGREP_COMMIT}" >&2
    exit 1
fi
cargo build --manifest-path "${src}/Cargo.toml" --release -p colgrep
install -m 0755 "${src}/target/release/colgrep" "${PA_STAGE}/usr/local/bin/colgrep"
rm -rf "${src}"

# 3. repomix (via npm)
echo "=== Installing repomix ${REPOMIX_VERSION} ==="
npm install -g --prefix="${PA_STAGE}/usr/local" "repomix@${REPOMIX_VERSION}"

# 4. tokencount wrapper
cat << 'EOF' > "${PA_STAGE}/usr/local/bin/tokencount"
#!/usr/bin/env bash
# Quick token counting wrapper using repomix
set -euo pipefail
exec repomix --token-count-encoding o200k_base "$@"
EOF
chmod 0755 "${PA_STAGE}/usr/local/bin/tokencount"

# Verification in build stage
"${PA_STAGE}/usr/local/bin/ast-grep" --version
"${PA_STAGE}/usr/local/bin/sg" --version
"${PA_STAGE}/usr/local/bin/colgrep" --version
PATH="${PA_STAGE}/usr/local/bin:${PATH}" "${PA_STAGE}/usr/local/bin/repomix" --version
PATH="${PA_STAGE}/usr/local/bin:${PATH}" "${PA_STAGE}/usr/local/bin/tokencount" --help

echo "=== code-intelligence capability build complete ==="
