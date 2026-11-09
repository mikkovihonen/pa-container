#!/bin/bash
set -euo pipefail
PA_STAGE="${PA_STAGE:-/out}"

pi_tarball="pi-coding-agent-${PI_VERSION}.tgz"
pi_url="https://registry.npmjs.org/@earendil-works/pi-coding-agent/-/pi-coding-agent-${PI_VERSION}.tgz"

curl -fsSL -o "/tmp/${pi_tarball}" "${pi_url}"
echo "${PI_SHA256}  /tmp/${pi_tarball}" | sha256sum -c -

npm install -g --prefix "${PA_STAGE}/usr/local" --ignore-scripts "/tmp/${pi_tarball}"
rm -f "/tmp/${pi_tarball}"
