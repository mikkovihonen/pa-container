#!/bin/bash
# Build CPython 3.15 from source and stage with uv and pip
set -euo pipefail

PA_STAGE="${PA_STAGE:-/out}"
mkdir -p "${PA_STAGE}/usr/local" /usr/src/python

cd /usr/src/python
curl -fsSL -o "Python-${PYTHON_VERSION}.tgz" "https://www.python.org/ftp/python/${PYTHON_VERSION}/Python-${PYTHON_VERSION}.tgz"
echo "${PYTHON_SHA256}  Python-${PYTHON_VERSION}.tgz" | sha256sum -c -
tar -xf "Python-${PYTHON_VERSION}.tgz"
cd "Python-${PYTHON_VERSION}"

./configure --prefix=/usr/local --enable-optimizations
make -j "$(nproc)"
make install
make install DESTDIR="${PA_STAGE}"

cd /
rm -rf /usr/src/python

py_minor="${PYTHON_VERSION%.*}"

# Create unversioned symlinks in builder's /usr/local
ln -sf "python${py_minor}" "/usr/local/bin/python"
ln -sf "python${py_minor}" "/usr/local/bin/python3"
ln -sf "pip${py_minor}" "/usr/local/bin/pip"
ln -sf "pip${py_minor}" "/usr/local/bin/pip3"

# Explicitly install pip and uv into staged prefix.
# ensurepip in `make install DESTDIR` skips pip because it detects the builder's /usr/local install as already satisfied.
# Installing with --ignore-installed ensures pip is properly written to $PA_STAGE.
/usr/local/bin/python3 -m pip install --root-user-action=ignore --root "${PA_STAGE}" --ignore-installed pip "uv==${UV_VERSION}"

# Create unversioned symlinks in staged tree
mkdir -p "${PA_STAGE}/usr/local/bin"
ln -sf "python${py_minor}" "${PA_STAGE}/usr/local/bin/python"
ln -sf "python${py_minor}" "${PA_STAGE}/usr/local/bin/python3"
ln -sf "pip${py_minor}" "${PA_STAGE}/usr/local/bin/pip"
ln -sf "pip${py_minor}" "${PA_STAGE}/usr/local/bin/pip3"

# Trim unnecessary tests and static archives
rm -rf "${PA_STAGE}/usr/local/lib/python${py_minor}/test"
rm -f "${PA_STAGE}/usr/local/lib/libpython${py_minor}.a"

# Verification
"${PA_STAGE}/usr/local/bin/python3" --version
"${PA_STAGE}/usr/local/bin/python3" -c 'import _zstd, bz2, ctypes, curses, lzma, readline, sqlite3, ssl, zlib'
"${PA_STAGE}/usr/local/bin/uv" --version
[ -x "${PA_STAGE}/usr/local/bin/pip" ]
[ -x "${PA_STAGE}/usr/local/bin/pip${py_minor}" ]
PYTHONPATH="${PA_STAGE}/usr/local/lib/python${py_minor}/site-packages" "${PA_STAGE}/usr/local/bin/python3" -m pip --version

echo "=== Python build complete ==="
