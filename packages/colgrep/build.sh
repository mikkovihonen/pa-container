#!/bin/bash
# Build colgrep multi-vector semantic code search CLI from source and stage it.
#
# Run from coding-agent-builder/Containerfile, as root, at image build time.
set -euo pipefail
PA_STAGE="${PA_STAGE:-/out}"
# legacy path
# legacy check
# shellcheck source=/dev/null
# common sourced

require_env COLGREP_VERSION COLGREP_COMMIT

src="/usr/src/colgrep"
echo "Cloning colgrep ${COLGREP_VERSION}"
git -c advice.detachedHead=false clone --quiet --depth 1 "https://github.com/lightonai/next-plaid.git" "${src}"
head="$(git -C "${src}" rev-parse HEAD)"
if [ "${head}" != "${COLGREP_COMMIT}" ]; then
    echo "ERROR: colgrep resolves to ${head}, expected ${COLGREP_COMMIT}." >&2
    exit 1
fi

cd "${src}"
cargo build --release -p colgrep
mkdir -p "${PA_STAGE}/usr/local/bin"
install -m755 target/release/colgrep "${PA_STAGE}/usr/local/bin/colgrep"
rm -rf "${src}" /root/.cargo/registry /root/.cargo/git

"${PA_STAGE}/usr/local/bin/colgrep" --version
stage_record "colgrep" "${COLGREP_VERSION}"

