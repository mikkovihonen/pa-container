#!/bin/bash
# Stage headless browser shared runtime libraries
set -euo pipefail
PA_STAGE="${PA_STAGE:-/out}"

mkdir -p "${PA_STAGE}/usr/lib64"
for lib in libcairo.so* libpango-*.so* libatk-*.so* libasound.so* libX11.so* libgbm.so* libnss3.so* libnspr4.so*; do
    for f in /usr/lib64/${lib}; do
        if [ -e "$f" ]; then
            cp -a "$f" "${PA_STAGE}/usr/lib64/"
        fi
    done
done

stage_record "browser-runtime" "1.0.0"
