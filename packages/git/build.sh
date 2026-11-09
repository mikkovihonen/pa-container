#!/bin/bash
# Build high-performance Git from source with libdeflate and PCRE2 support and stage it.
#
# Run from ACP package builder, as root, at image build time.
set -euo pipefail
PA_STAGE="${PA_STAGE:-/out}"

require_env GIT_VERSION GIT_SHA256

tarball="git-${GIT_VERSION}.tar.xz"
fetch_verified "https://mirrors.edge.kernel.org/pub/software/scm/git/${tarball}" "${GIT_SHA256}" "/tmp/${tarball}"
src="/usr/src/git-${GIT_VERSION}"
mkdir -p "${src}"
tar -C /usr/src -xJf "/tmp/${tarball}"
rm -f "/tmp/${tarball}"

cd "${src}"
make -j "$(mem_capped_jobs 300)" \
    prefix="${PA_STAGE}/usr/local" \
    USE_LIBDEFLATE=YesPlease \
    USE_LIBPCRE2=YesPlease \
    NO_TCLTK=YesPlease \
    INSTALL_SYMLINKS=1 \
    all
make prefix="${PA_STAGE}/usr/local" NO_TCLTK=YesPlease install
rm -rf "${src}"

"${PA_STAGE}/usr/local/bin/git" --version
stage_record "git" "${GIT_VERSION}"

