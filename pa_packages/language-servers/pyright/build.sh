#!/bin/bash
# Install and stage pyright
set -euo pipefail
PA_STAGE="${PA_STAGE:-/out}"

mkdir -p "${PA_STAGE}/usr/local"
npm install -g --prefix="${PA_STAGE}/usr/local" pyright

"${PA_STAGE}/usr/local/bin/pyright" --version
stage_record "pyright" "latest"
