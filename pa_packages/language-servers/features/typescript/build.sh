#!/bin/bash
# Install and stage typescript-language-server
set -euo pipefail
PA_STAGE="${PA_STAGE:-/out}"

mkdir -p "${PA_STAGE}/usr/local"
npm install -g --prefix="${PA_STAGE}/usr/local" typescript typescript-language-server

"${PA_STAGE}/usr/local/bin/typescript-language-server" --version
stage_record "typescript" "latest"
