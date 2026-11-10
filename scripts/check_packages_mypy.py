#!/usr/bin/env python3
"""Run strict mypy type check on all ACP package host modules."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGES_DIR = REPO_ROOT / "packages"


def main() -> int:
    failed = False
    package_hosts = sorted(PACKAGES_DIR.glob("*/host"))

    if not package_hosts:
        print("No package host directories found.")
        return 0

    env = dict(os.environ)
    env["MYPYPATH"] = str(REPO_ROOT / "src")

    for host_dir in package_hosts:
        pkg_name = host_dir.parent.name
        cmd = [
            sys.executable,
            "-m",
            "mypy",
            "--config-file",
            str(REPO_ROOT / "pyproject.toml"),
            str(host_dir),
        ]
        result = subprocess.run(cmd, cwd=str(REPO_ROOT), env=env, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"❌ ACP package '{pkg_name}' host type check failed:")
            print(result.stdout)
            print(result.stderr)
            failed = True
        else:
            print(f"✅ ACP package '{pkg_name}' passed strict type check.")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
