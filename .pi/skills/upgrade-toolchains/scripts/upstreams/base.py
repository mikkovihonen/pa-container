from __future__ import annotations

import hashlib
import json
import re
import sys
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

sys.dont_write_bytecode = True

REPO_ROOT = Path(__file__).resolve().parents[4]
PACKAGES_DIR = REPO_ROOT / "pa_packages"
CONTAINERFILE = PACKAGES_DIR

# When False (default for --check audits), large binary archive downloads are skipped.
# When True (during --upgrade), full downloads occur to compute new sha256 checksums.
IS_UPGRADE_MODE: bool = False


@dataclass
class ToolReleaseInfo:
    """Resolved release information and Containerfile ARGs for a tool."""

    tool: str
    version: str
    args: dict[str, str] = field(default_factory=dict)
    category: str = "tools"
    release_url: str | None = None


def get_containerfile_args() -> dict[str, str]:
    """Parse all version declarations into a dictionary."""
    if CONTAINERFILE.is_file():
        args: dict[str, str] = {}
        pattern = re.compile(r"^ARG\s+([A-Za-z0-9_]+)=(.*)$", re.MULTILINE)
        for m in pattern.finditer(CONTAINERFILE.read_text()):
            args[m.group(1).strip()] = m.group(2).strip()
        return args
    if PACKAGES_DIR.is_dir():
        import yaml

        args = {}
        for pkg_dir in PACKAGES_DIR.iterdir():
            manifest = pkg_dir / "package.yaml"
            if manifest.is_file():
                try:
                    data = yaml.safe_load(manifest.read_text())
                    if isinstance(data, dict):
                        pkg_data = data.get("package", {})
                        v = str(pkg_data.get("version", ""))
                        name = str(pkg_data.get("name", pkg_dir.name))
                        if name == "tree-sitter-cli":
                            args["TREE_SITTER_VERSION"] = v
                        elif name == "aardvark-dns":
                            args["AARDVARK_VERSION"] = v
                        else:
                            args[f"{name.replace('-', '_').upper()}_VERSION"] = v
                except Exception:
                    pass
        return args
    return {}


def fetch_url(url: str, timeout: int = 30) -> bytes:
    """Fetch binary response from a URL."""
    req = urllib.request.Request(url, headers={"User-Agent": "pa-container-upgrade-tools"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def fetch_json(url: str, timeout: int = 30) -> dict:
    """Fetch and parse JSON from a URL."""
    req = urllib.request.Request(url, headers={"User-Agent": "pa-container-upgrade-tools"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def sha256_of_url(url: str, timeout: int = 120) -> str:
    """Stream a URL and compute its SHA256 hex digest."""
    req = urllib.request.Request(url, headers={"User-Agent": "pa-container-upgrade-tools"})
    h = hashlib.sha256()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        while chunk := resp.read(65536):
            h.update(chunk)
    return h.hexdigest()


def parse_version_tuple(v: str) -> tuple[int, ...]:
    """Extract a numeric comparison tuple from a version tag string.

    Examples:
        'v2.36.0' -> (2, 36, 0)
        'llvmorg-19.1.7' -> (19, 1, 7)
        'gopls/v0.18.1' -> (0, 18, 1)
        '2025-02-24' -> (2025, 2, 24)
    """
    clean = re.sub(r"^(?:llvmorg-|gopls/|v)", "", v.strip())
    parts = re.findall(r"\d+", clean)
    if not parts:
        return (0,)
    return tuple(int(p) for p in parts)

