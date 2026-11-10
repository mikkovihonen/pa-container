#!/bin/bash
# Build Ruby from source with Rust-based YJIT and jemalloc and stage it.
#
# Run from ACP package builder, as root, at image build time.
set -euo pipefail
PA_STAGE="${PA_STAGE:-/out}"

require_env RUBY_VERSION RUBY_SHA256

tarball="ruby-${RUBY_VERSION}.tar.xz"
fetch_verified "https://cache.ruby-lang.org/pub/ruby/3.4/${tarball}" "${RUBY_SHA256}" "/tmp/${tarball}"

src="/usr/src/ruby-${RUBY_VERSION}"
mkdir -p "${src}"
tar -C /usr/src -xJf "/tmp/${tarball}"
rm -f "/tmp/${tarball}"

cd "${src}"
./configure --prefix="${PA_STAGE}/usr/local" \
    --enable-yjit \
    --with-jemalloc \
    --disable-install-doc
make -j "$(mem_capped_jobs 400)"
make install
mkdir -p "${PA_STAGE}/usr/lib64"
cp -a /usr/lib64/libjemalloc.so* "${PA_STAGE}/usr/lib64/"
rm -rf "${src}"

"${PA_STAGE}/usr/local/bin/ruby" --version
stage_record "ruby" "${RUBY_VERSION}"

