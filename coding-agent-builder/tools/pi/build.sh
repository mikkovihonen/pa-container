#!/bin/bash
# Download, verify, and stage the Pi coding agent package.
#
# Run from coding-agent-builder/Containerfile, as root, at image build time.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMMON_SH="${SCRIPT_DIR}/../../common.sh"
[ -f "${COMMON_SH}" ] || COMMON_SH="/build/common.sh"
# shellcheck source=/dev/null
source "${COMMON_SH}"

require_env PI_VERSION PI_SHA256

pi_tarball="pi-coding-agent-${PI_VERSION}.tgz"
pi_url="https://registry.npmjs.org/@earendil-works/pi-coding-agent/-/pi-coding-agent-${PI_VERSION}.tgz"

fetch_verified "${pi_url}" "${PI_SHA256}" "/tmp/${pi_tarball}"

npm install -g --prefix "${PA_STAGE}/usr/local" --ignore-scripts "/tmp/${pi_tarball}"
rm -f "/tmp/${pi_tarball}"

stage_record "pi" "${PI_VERSION}"
