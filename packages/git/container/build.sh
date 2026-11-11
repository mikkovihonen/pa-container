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
    prefix=/usr/local \
    sysconfdir=/etc \
    USE_LIBDEFLATE=YesPlease \
    USE_LIBPCRE2=YesPlease \
    NO_TCLTK=YesPlease \
    NO_RUST=YesPlease \
    INSTALL_SYMLINKS=1 \
    all
make prefix=/usr/local sysconfdir=/etc DESTDIR="${PA_STAGE}" NO_TCLTK=YesPlease NO_RUST=YesPlease install
cd /
rm -rf "${src}"

# Install mcp-server-git into stage
echo "=== Installing mcp-server-git ==="
/usr/local/bin/python3 -m pip install --root-user-action=ignore --root "${PA_STAGE}" --ignore-installed mcp-server-git

# Stage entrypoint hooks
if [ -d /build/entrypoint.d/root ]; then
    mkdir -p "${PA_STAGE}/usr/local/share/pa-container/entrypoint.d/root"
    cp -a /build/entrypoint.d/root/* "${PA_STAGE}/usr/local/share/pa-container/entrypoint.d/root/"
    chmod +x "${PA_STAGE}/usr/local/share/pa-container/entrypoint.d/root/"*.sh 2>/dev/null || true
fi

if [ -d /build/entrypoint.d/agent ]; then
    mkdir -p "${PA_STAGE}/usr/local/share/pa-container/entrypoint.d/agent"
    cp -a /build/entrypoint.d/agent/* "${PA_STAGE}/usr/local/share/pa-container/entrypoint.d/agent/"
    chmod +x "${PA_STAGE}/usr/local/share/pa-container/entrypoint.d/agent/"*.sh 2>/dev/null || true
fi

mkdir -p "${PA_STAGE}/etc" "${PA_STAGE}/usr/local/etc"

"${PA_STAGE}/usr/local/bin/git" --version
stage_record "git" "${GIT_VERSION}"
