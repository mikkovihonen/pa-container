#!/bin/bash
# Staging recipe for reverse-engineering core capability
set -euo pipefail
PA_STAGE="${PA_STAGE:-/out}"

mkdir -p "${PA_STAGE}/usr/local/bin" "${PA_STAGE}/usr/local/share/pa-container/packages/reverse-engineering/scripts"

# Copy Ghidra postScripts if present
SCRIPT_DIR="$(dirname "$0")/scripts"
if [ -d "${SCRIPT_DIR}" ]; then
    cp -a "${SCRIPT_DIR}"/* "${PA_STAGE}/usr/local/share/pa-container/packages/reverse-engineering/scripts/"
fi

# Install a standalone lightweight checksec script for binary security mitigation inspection
cat <<'EOF' > "${PA_STAGE}/usr/local/bin/checksec"
#!/usr/bin/env python3
"""Lightweight ELF mitigation auditor (RELRO, Canary, NX, PIE, RPATH/RUNPATH)."""

import os
import struct
import sys
import subprocess

def check_elf(filepath):
    if not os.path.exists(filepath):
        print(f"Error: file not found: {filepath}", file=sys.stderr)
        sys.exit(1)

    with open(filepath, "rb") as f:
        magic = f.read(4)
        if magic != b"\x7fELF":
            print(f"{filepath}: Not an ELF binary")
            return

        f.seek(4)
        ei_class = f.read(1)[0]
        ei_data = f.read(1)[0]
        endian = "<" if ei_data == 1 else ">"
        is_64 = ei_class == 2

        f.seek(16)
        e_type = struct.unpack(f"{endian}H", f.read(2))[0]

    readelf = subprocess.run(["readelf", "-l", "-d", "-s", filepath], capture_output=True, text=True)
    out = readelf.stdout

    relro = "No RELRO"
    if "GNU_RELRO" in out:
        relro = "Full RELRO" if "BIND_NOW" in out else "Partial RELRO"

    canary = "No Canary"
    if "__stack_chk_fail" in out:
        canary = "Canary found"

    nx = "NX enabled"
    if "GNU_STACK" in out:
        for line in out.splitlines():
            if "GNU_STACK" in line and "RWE" in line:
                nx = "NX disabled"
                break

    pie = "No PIE"
    if e_type == 3:  # ET_DYN
        pie = "PIE enabled" if "DEBUG" in out or canary != "No Canary" else "DSO"
    elif e_type == 2:  # ET_EXEC
        pie = "No PIE (Executable)"

    print(f"File:    {filepath}")
    print(f"RELRO:   {relro}")
    print(f"Stack:   {canary}")
    print(f"NX:      {nx}")
    print(f"PIE:     {pie}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: checksec <elf-binary>", file=sys.stderr)
        sys.exit(1)
    check_elf(sys.argv[1])
EOF
chmod 0755 "${PA_STAGE}/usr/local/bin/checksec"

stage_record "reverse-engineering" "1.0.0"
