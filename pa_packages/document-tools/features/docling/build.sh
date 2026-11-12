#!/bin/bash
# Install and stage Docling neural document parsing tool.
set -euo pipefail
PA_STAGE="${PA_STAGE:-/out}"

mkdir -p "${PA_STAGE}/usr/local"
uv pip install --system --prefix="${PA_STAGE}/usr/local" docling

stage_record "docling" "latest"
