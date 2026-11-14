#!/usr/bin/env python3
"""Validate version consistency across git tag, Cargo.toml, and pyproject.toml."""

from __future__ import annotations

import argparse
import subprocess
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
TAG_PREFIX = "v"


def _info(msg: str) -> None:
    print(f"  ✓ {msg}")


def _error(msg: str) -> None:
    print(f"  ✗ {msg}")


def get_git_tag_version() -> str | None:
    """Read the git tag on HEAD if present."""
    try:
        res = subprocess.run(
            ["git", "describe", "--tags", "--exact-match", "HEAD"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode == 0:
            tag = res.stdout.strip()
            if tag.startswith(TAG_PREFIX):
                return tag[len(TAG_PREFIX) :]
            return tag
    except Exception:
        pass
    return None


def get_cargo_workspace_version() -> str | None:
    """Read workspace package version from Cargo.toml."""
    cargo_path = REPO_ROOT / "Cargo.toml"
    if not cargo_path.exists():
        return None
    try:
        with cargo_path.open("rb") as f:
            data = tomllib.load(f)
        val = data.get("workspace", {}).get("package", {}).get("version")
        return str(val) if val else None
    except Exception:
        return None


def get_pyproject_version() -> str | None:
    """Read project version from pyproject.toml."""
    pyproject_path = REPO_ROOT / "pyproject.toml"
    if not pyproject_path.exists():
        return None
    try:
        with pyproject_path.open("rb") as f:
            data = tomllib.load(f)
        val = data.get("project", {}).get("version")
        return str(val) if val else None
    except Exception:
        return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--new-version",
        help="Target version to validate against (used during release preparation).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    all_pass = True

    print("PA-Container 2.0 Version Consistency Gate")
    print("=========================================")

    cargo_ver = get_cargo_workspace_version()
    pyproject_ver = get_pyproject_version()
    git_tag_ver = get_git_tag_version()

    print(f"Cargo.toml workspace version: {cargo_ver}")
    print(f"pyproject.toml version:       {pyproject_ver}")
    print(f"Git tag on HEAD:              {git_tag_ver or '(none)'}")
    print()

    # Check 1: Cargo.toml version present
    if not cargo_ver:
        _error("Cargo.toml is missing [workspace.package] version")
        all_pass = False
    else:
        _info(f"Cargo.toml workspace version present: {cargo_ver}")

    # Check 2: pyproject.toml matches Cargo.toml
    if pyproject_ver != cargo_ver:
        _error(f"pyproject.toml version ({pyproject_ver}) does not match Cargo.toml ({cargo_ver})")
        all_pass = False
    else:
        _info(f"pyproject.toml version matches Cargo.toml ({cargo_ver})")

    # Check 3: If target version supplied, verify match
    target_ver = args.new_version or git_tag_ver
    if target_ver:
        if cargo_ver != target_ver:
            _error(f"Cargo.toml version ({cargo_ver}) does not match target version ({target_ver})")
            all_pass = False
        else:
            _info(f"Target version matches workspace ({target_ver})")

    # Check 4: Defaults directory exists
    defaults_dir = REPO_ROOT / "defaults"
    if not (defaults_dir / "config.yaml").is_file():
        _error(f"Missing required defaults config: {defaults_dir / 'config.yaml'}")
        all_pass = False
    else:
        _info("defaults/config.yaml is present")

    print()
    if all_pass:
        print("All version checks passed.")
        return 0
    else:
        print("Validation FAILED.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
