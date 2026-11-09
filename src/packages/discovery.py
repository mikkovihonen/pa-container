from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from packages.manifest import PackageManifest

sys.dont_write_bytecode = True

from logging_driver import LogCategory, get_category_logger
from packages.manifest import load_package_manifest

logger = get_category_logger(__name__, LogCategory.BUILD)

"""Package discovery, manifest resolution, and content-hash computation."""


def get_packages_dir(repo_root: Path | None = None) -> Path:
    """Return the absolute path to the root packages/ directory."""
    if repo_root is None:
        repo_root = Path(__file__).resolve().parent.parent.parent
    return repo_root / "packages"


def get_package_dir(package_name: str, repo_root: Path | None = None) -> Path:
    """Return the directory path for a specific package."""
    return get_packages_dir(repo_root) / package_name


def package_to_image_tag(package_name: str) -> str:
    """Return the local container image tag for an Agent Capability Package."""
    clean_name = package_name.lower().replace("_", "-")
    return f"pa-container-pkg-{clean_name}:local"


def discover_packages(repo_root: Path | None = None) -> dict[str, PackageManifest]:
    """Discover and parse all available package manifests under packages/*/package.yaml."""
    packages_dir = get_packages_dir(repo_root)
    if not packages_dir.is_dir():
        return {}

    manifests: dict[str, PackageManifest] = {}
    for entry in sorted(packages_dir.iterdir()):
        if entry.is_dir():
            manifest_file = entry / "package.yaml"
            if manifest_file.is_file():
                try:
                    manifest = load_package_manifest(manifest_file)
                    manifests[manifest.name] = manifest
                except Exception as e:
                    logger.warning(f"Failed to load package manifest at {manifest_file}: {e}")
    return manifests


def compute_package_hash(package_name: str, repo_root: Path | None = None) -> str:
    """Compute content hash for an Agent Capability Package based on its directory contents."""
    pkg_dir = get_package_dir(package_name, repo_root)
    if not pkg_dir.is_dir():
        # Package directory not found; return stable hash of package name
        return hashlib.sha256(f"missing:{package_name}".encode()).hexdigest()[:16]

    hasher = hashlib.sha256()
    hasher.update(package_name.encode())

    # Deterministically walk all regular files in the package directory
    for file_path in sorted(pkg_dir.rglob("*")):
        if file_path.is_file() and not file_path.name.startswith("."):
            rel_path = file_path.relative_to(pkg_dir)
            hasher.update(str(rel_path).encode())
            try:
                hasher.update(file_path.read_bytes())
            except OSError as e:
                logger.warning(f"Could not read package file {file_path} for hashing: {e}")

    return hasher.hexdigest()[:16]
