from __future__ import annotations

import hashlib
import sys
from collections.abc import Mapping, Sequence
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


def package_to_image_tag(package_name: str, features: list[str] | set[str] | None = None) -> str:
    """Return the local container image tag for an Agent Capability Package."""
    clean_name = package_name.lower().replace("_", "-")
    if not features:
        return f"pa-container-pkg-{clean_name}:local"
    feat_str = "--".join(sorted(features))
    return f"pa-container-pkg-{clean_name}--{feat_str}:local"


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


def get_core_packages(repo_root: Path | None = None) -> list[str]:
    """Return the sorted list of package names marked declaratively with core: true."""
    manifests = discover_packages(repo_root)
    return sorted([name for name, m in manifests.items() if m.core])


def compute_package_hash(
    package_name: str,
    repo_root: Path | None = None,
    features: list[str] | set[str] | None = None,
) -> str:
    """Compute content hash for an Agent Capability Package based on its directory contents and active features."""
    pkg_dir = get_package_dir(package_name, repo_root)
    if not pkg_dir.is_dir():
        # Package directory not found; return stable hash of package name
        return hashlib.sha256(f"missing:{package_name}".encode()).hexdigest()[:16]

    hasher = hashlib.sha256()
    hasher.update(package_name.encode())
    if features:
        hasher.update(f"features:{','.join(sorted(features))}".encode())

    # Deterministically walk all regular files in the package directory affecting container image
    for file_path in sorted(pkg_dir.rglob("*")):
        if not file_path.is_file() or file_path.name.startswith("."):
            continue
        rel_path = file_path.relative_to(pkg_dir)
        parts = rel_path.parts
        # Host Python code and tests do not affect container image layers
        if "host" in parts or "__pycache__" in parts:
            continue
        hasher.update(str(rel_path).encode())
        try:
            hasher.update(file_path.read_bytes())
        except OSError as e:
            logger.warning(f"Could not read package file {file_path} for hashing: {e}")

    return hasher.hexdigest()[:16]


def collect_distro_packages(
    packages_map: Mapping[str, Sequence[str] | None] | Sequence[tuple[str, Sequence[str] | None]],
    manifests: dict[str, PackageManifest] | None = None,
    repo_root: Path | None = None,
) -> list[str]:
    """Collect and deduplicate all distro packages required by the given packages and active features.

    Args:
        packages_map: Mapping of package names to features or list of (pkg, feats) tuples.
        manifests: Optional pre-loaded package manifests mapping.
        repo_root: Optional repository root path.

    Returns:
        Sorted list of unique distro package names to install via system package manager.
    """
    if manifests is None:
        manifests = discover_packages(repo_root)

    items: Sequence[tuple[str, Sequence[str] | None]] = (
        list(packages_map.items()) if isinstance(packages_map, Mapping) else packages_map
    )

    pkgs_set: set[str] = set()
    for pkg_name, active_feats in items:
        manifest = manifests.get(pkg_name)
        if manifest is None:
            pdir = get_package_dir(pkg_name, repo_root)
            mfile = pdir / "package.yaml"
            if mfile.is_file():
                try:
                    manifest = load_package_manifest(mfile)
                except Exception:
                    manifest = None
        if manifest is None:
            continue

        if manifest.payload.packages:
            pkgs_set.update(manifest.payload.packages)
        feat_set = set(active_feats) if active_feats is not None else None
        for feat_name, feat in manifest.features.items():
            is_active = (feat_name in feat_set) if feat_set is not None else feat.default
            if is_active and feat.payload.packages:
                pkgs_set.update(feat.payload.packages)

    return sorted(p for p in pkgs_set if p)
