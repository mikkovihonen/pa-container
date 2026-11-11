#!/bin/bash
# Base build script for unified agents capability package.
set -euo pipefail
PA_STAGE="${PA_STAGE:-/out}"

mkdir -p "${PA_STAGE}/usr/local/share/pa-container/packages/agents"
stage_record "agents" "1.0.0"
