#!/bin/bash
# Download, verify, and install the Pi coding agent via npm.
set -euo pipefail
PA_STAGE="${PA_STAGE:-/out}"

require_env PI_VERSION PI_SHA256

pi_tarball="pi-coding-agent-${PI_VERSION}.tgz"
pi_url="https://registry.npmjs.org/@earendil-works/pi-coding-agent/-/pi-coding-agent-${PI_VERSION}.tgz"

fetch_verified "${pi_url}" "${PI_SHA256}" "/tmp/${pi_tarball}"

npm install -g --prefix "${PA_STAGE}/usr/local" --ignore-scripts "/tmp/${pi_tarball}"
rm -f "/tmp/${pi_tarball}"

"${PA_STAGE}/usr/local/bin/pi" --version
stage_record "pi" "${PI_VERSION}"
