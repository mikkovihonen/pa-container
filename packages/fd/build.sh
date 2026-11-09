#!/bin/bash
# Build fd from source and stage it as /usr/local/bin/fd.
#
# Run from coding-agent-builder/Containerfile, as root, at image build time.
set -euo pipefail
PA_STAGE="${PA_STAGE:-/out}"
# legacy path
# legacy check
# shellcheck source=/dev/null
# common sourced

require_env FD_VERSION FD_COMMIT

src="/usr/src/fd"
clone_verified "https://github.com/sharkdp/fd.git" "${FD_VERSION}" "${FD_COMMIT}" "${src}"

cd "${src}"
cargo build --release
mkdir -p "${PA_STAGE}/usr/local/bin"
install -m755 target/release/fd "${PA_STAGE}/usr/local/bin/fd"
rm -rf "${src}" /root/.cargo/registry /root/.cargo/git

"${PA_STAGE}/usr/local/bin/fd" --version
stage_record "fd" "${FD_VERSION}"

