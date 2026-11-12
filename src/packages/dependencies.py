from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from packages.manifest import PackageManifest

sys.dont_write_bytecode = True

from logging_driver import LogCategory, get_category_logger
from packages.discovery import discover_packages

logger = get_category_logger(__name__, LogCategory.BUILD)

"""Transitive dependency resolution and topological sorting for Agent Capability Packages (ACPs)."""


def resolve_package_dependencies(
    packages_map: Mapping[str, Sequence[str] | None],
    manifests: dict[str, PackageManifest] | None = None,
    repo_root: Path | None = None,
    include_build_packages: bool = True,
) -> dict[str, list[str]]:
    """Transitively resolve all package and feature runtime and build tool dependencies in topological order.

    Args:
        packages_map: Mapping of package names to active features (e.g. {"agents": ["pi"]}).
        manifests: Optional pre-loaded package manifests mapping.
        repo_root: Optional repository root path.
        include_build_packages: Whether to include build-time tool dependencies (payload.build_packages).

    Returns:
        Topologically sorted dictionary of {package_name: [active_features]} where
        dependencies precede dependent packages.

    Raises:
        ValueError: If a circular dependency loop is detected.
    """
    if manifests is None:
        manifests = discover_packages(repo_root)

    # Initialize resolved features with copies of incoming features
    resolved_features: dict[str, set[str]] = {}
    for pkg_name, feats in packages_map.items():
        clean_name = str(pkg_name).strip()
        if not clean_name:
            continue
        feat_set = {str(f).strip() for f in (feats or []) if str(f).strip()}
        resolved_features[clean_name] = feat_set

    # Transitive expansion
    direct_deps_graph: dict[str, set[str]] = {}
    queue: list[str] = list(resolved_features.keys())
    visited_for_expansion: set[str] = set()

    while queue:
        current_pkg = queue.pop(0)
        if current_pkg in visited_for_expansion:
            continue
        visited_for_expansion.add(current_pkg)

        current_deps: set[str] = set()
        manifest = manifests.get(current_pkg)
        if manifest is not None:
            # Package-level runtime and build-time tool dependencies
            current_deps.update(manifest.runtime.dependencies)
            if include_build_packages:
                current_deps.update(manifest.payload.build_packages)

            # Feature-level runtime and build-time tool dependencies for active features
            active_feats = resolved_features.get(current_pkg, set())
            for feat_name, feat in manifest.features.items():
                if feat_name in active_feats or (not active_feats and feat.default):
                    current_deps.update(feat.runtime.dependencies)
                    if include_build_packages:
                        current_deps.update(feat.payload.build_packages)

        direct_deps_graph[current_pkg] = current_deps

        for dep in current_deps:
            if dep not in resolved_features:
                dep_manifest = manifests.get(dep)
                default_feats: set[str] = set()
                if dep_manifest is not None:
                    default_feats = {f_name for f_name, f_obj in dep_manifest.features.items() if f_obj.default}
                resolved_features[dep] = default_feats
                queue.append(dep)

    # Topological sort using post-order DFS
    sorted_order: list[str] = []
    visiting: set[str] = set()
    visited: set[str] = set()

    def _dfs(node: str, path: list[str]) -> None:
        if node in visiting:
            cycle = " -> ".join(path + [node])
            raise ValueError(f"Circular package dependency detected: {cycle}")
        if node in visited:
            return

        visiting.add(node)
        for dep in sorted(direct_deps_graph.get(node, set())):
            _dfs(dep, path + [node])

        visiting.remove(node)
        visited.add(node)
        sorted_order.append(node)

    for pkg in sorted(resolved_features.keys()):
        if pkg not in visited:
            _dfs(pkg, [])

    return {pkg: sorted(resolved_features[pkg]) for pkg in sorted_order}
