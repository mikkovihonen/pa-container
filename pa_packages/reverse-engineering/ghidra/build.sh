#!/bin/bash
# Staging recipe for Ghidra GUI application
set -euo pipefail
PA_STAGE="${PA_STAGE:-/out}"

mkdir -p "${PA_STAGE}/usr/local/share/ghidra" "${PA_STAGE}/usr/local/bin" "${PA_STAGE}/usr/share/applications"

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

cat <<'EOF' > "${PA_STAGE}/usr/local/bin/ghidra"
#!/bin/bash
GHIDRA_DIR="${GHIDRA_INSTALL_DIR:-/usr/local/share/ghidra}"
exec "${GHIDRA_DIR}/ghidraRun" "$@"
EOF
chmod 0755 "${PA_STAGE}/usr/local/bin/ghidra"

cat <<'EOF' > "${PA_STAGE}/usr/share/applications/ghidra.desktop"
[Desktop Entry]
Version=1.0
Type=Application
Name=Ghidra
GenericName=Software Reverse Engineering Suite
Comment=NSA Software Reverse Engineering Suite
Exec=/usr/local/bin/ghidra
Icon=/usr/local/share/ghidra/support/ghidra.png
Terminal=false
Categories=Development;Security;
EOF

stage_record "ghidra" "${GHIDRA_VERSION}"
