#!/bin/bash
# Staging recipe for Ghidra headless batch capability
set -euo pipefail
PA_STAGE="${PA_STAGE:-/out}"

mkdir -p "${PA_STAGE}/usr/local/share/ghidra" "${PA_STAGE}/usr/local/bin"

zip_name="ghidra_${GHIDRA_VERSION}_PUBLIC_${GHIDRA_BUILD_DATE}.zip"
ghidra_url="https://github.com/NationalSecurityAgency/ghidra/releases/download/Ghidra_${GHIDRA_VERSION}_build/${zip_name}"

if [ ! -f "${PA_STAGE}/usr/local/share/ghidra/ghidraRun" ]; then
    tmp_dir="$(mktemp -d)"
    fetch_verified "${ghidra_url}" "${GHIDRA_SHA256}" "${tmp_dir}/${zip_name}"
    unzip -q "${tmp_dir}/${zip_name}" -d "${tmp_dir}"
    extracted_dir="${tmp_dir}/ghidra_${GHIDRA_VERSION}_PUBLIC"
    cp -a "${extracted_dir}"/* "${PA_STAGE}/usr/local/share/ghidra/"
    rm -rf "${tmp_dir}"
fi

cat <<'EOF' > "${PA_STAGE}/usr/local/bin/ghidra-headless"
#!/bin/bash
GHIDRA_DIR="${GHIDRA_INSTALL_DIR:-/usr/local/share/ghidra}"
exec "${GHIDRA_DIR}/support/analyzeHeadless" "$@"
EOF
chmod 0755 "${PA_STAGE}/usr/local/bin/ghidra-headless"

cat <<'EOF' > "${PA_STAGE}/usr/local/bin/ghidra-decompile"
#!/bin/bash
# Quick one-shot headless decompilation wrapper
set -euo pipefail
if [ $# -lt 1 ]; then
    echo "Usage: ghidra-decompile <binary-path> [function-name-or-address]" >&2
    exit 1
fi
TARGET_BIN="$(realpath "$1")"
FUNC_TARGET="${2:-}"
TMP_PROJ_DIR="$(mktemp -d /tmp/ghidra_proj_XXXXXX)"
TMP_PROJ_NAME="decompile_tmp"
GHIDRA_DIR="${GHIDRA_INSTALL_DIR:-/usr/local/share/ghidra}"
SCRIPT_DIR="/usr/local/share/pa-container/packages/reverse-engineering/scripts"

trap 'rm -rf "${TMP_PROJ_DIR}"' EXIT

if [ -n "${FUNC_TARGET}" ]; then
    "${GHIDRA_DIR}/support/analyzeHeadless" "${TMP_PROJ_DIR}" "${TMP_PROJ_NAME}" \
        -import "${TARGET_BIN}" -scriptPath "${SCRIPT_DIR}" \
        -postScript decompile_function.py "${FUNC_TARGET}" -deleteProject -readOnly
else
    "${GHIDRA_DIR}/support/analyzeHeadless" "${TMP_PROJ_DIR}" "${TMP_PROJ_NAME}" \
        -import "${TARGET_BIN}" -scriptPath "${SCRIPT_DIR}" \
        -postScript export_symbols.py -deleteProject -readOnly
fi
EOF
chmod 0755 "${PA_STAGE}/usr/local/bin/ghidra-decompile"

stage_record "ghidra-headless" "${GHIDRA_VERSION}"
