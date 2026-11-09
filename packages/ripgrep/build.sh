#!/bin/bash
set -euo pipefail
PA_STAGE="${PA_STAGE:-/out}"

git clone --depth 1 --branch "${RIPGREP_VERSION}" https://github.com/BurntSushi/ripgrep.git /tmp/ripgrep
cd /tmp/ripgrep
cargo build --release --features 'pcre2'
mkdir -p "${PA_STAGE}/usr/local/bin"
install -m 0755 target/release/rg "${PA_STAGE}/usr/local/bin/rg"
rm -rf /tmp/ripgrep /root/.cargo
"${PA_STAGE}/usr/local/bin/rg" --version
