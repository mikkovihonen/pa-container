#!/bin/bash
# Build the mold high-speed linker from source and stage it.
#
# Run from ACP package builder, as root, at image build time.
set -euo pipefail
PA_STAGE="${PA_STAGE:-/out}"

require_env MOLD_VERSION MOLD_COMMIT

src="/usr/src/mold"
clone_verified "https://github.com/rui314/mold.git" "${MOLD_VERSION}" "${MOLD_COMMIT}" "${src}"

mkdir -p /tmp/mold-build
cmake -DCMAKE_BUILD_TYPE=Release \
      -DCMAKE_INSTALL_PREFIX="${PA_STAGE}/usr/local" \
      -DMOLD_USE_SYSTEM_MIMALLOC=OFF \
      -DMOLD_LTO=ON \
      -B /tmp/mold-build -S "${src}"

cmake --build /tmp/mold-build -j "$(mem_capped_jobs 400)"
cmake --install /tmp/mold-build
rm -rf /tmp/mold-build "${src}"

"${PA_STAGE}/usr/local/bin/mold" --version
stage_record "mold" "${MOLD_VERSION}"

