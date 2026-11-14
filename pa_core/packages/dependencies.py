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

REMOVED_LEGACY_PACKAGES: dict[str, str] = {
    "python": "languages/python",
    "node": "languages/node",
    "c-cpp": "languages/c-cpp",
    "go": "languages/go",
    "ruby": "languages/ruby",
    "rust": "languages/rust",
    "zig": "languages/zig",
    "pi": "agents/pi",
    "opencode": "agents/opencode",
    "claude": "agents/claude",
    "antigravity": "agents/antigravity",
    "chromium": "browser/chromium",
    "chromium-headless": "browser/chromium-headless",
    "vips": "image-tools/vips",
    "jxl-heif": "image-tools/jxl-heif",
    "gmic": "image-tools/gmic",
    "trimesh": "3d-tools/trimesh",
    "blender": "3d-tools/blender",
    "meshlab": "3d-tools/meshlab",
    "openscad": "3d-tools/openscad",
    "whisper": "sound-tools/whisper",
    "docling": "document-tools/docling",
    "ocrmypdf": "ocr-tools/ocrmypdf",
    "ghidra-headless": "reverse-engineering/ghidra-headless",
    "ghidra": "reverse-engineering/ghidra",
    "emulation": "reverse-engineering/emulation",
    "qdrant": "vector-storage/qdrant",
    "wayland": "virtual-desktop/wayland",
    "x11": "virtual-desktop/x11",
    "pyright": "language-servers/pyright",
    "typescript": "language-servers/typescript",
    "clangd": "language-servers/clangd",
    "zls": "language-servers/zls",
    "rust-analyzer": "language-servers/rust-analyzer",
    "github": "source-control/github",
    "gitlab": "source-control/gitlab",
    "t3": "agent-orchestrators/t3",
    "gitea": "source-control/gitea",
    "cafe": "source-control/cafe",
    "azure-devops": "source-control/azure-devops",
    "bitbucket": "source-control/bitbucket",
}

"""Transitive dependency resolution and topological sorting for Agent Capability Packages (ACPs)."""


def resolve_package_dependencies(
    packages_map: Mapping[str, Sequence[str] | None] | Sequence[str],
    manifests: dict[str, PackageManifest] | None = None,
    repo_root: Path | None = None,
    include_build_packages: bool = True,
) -> dict[str, list[str]]:
    """Transitively resolve all package runtime and build tool dependencies in topological order.

    Args:
        packages_map: Mapping of package names or list of package names.
        manifests: Optional pre-loaded package manifests mapping.
        repo_root: Optional repository root path.
        include_build_packages: Whether to include build-time tool dependencies (payload.build_packages).

    Returns:
        Topologically sorted dictionary of {package_name: []} where
        dependencies precede dependent packages.

    Raises:
        ValueError: If a circular dependency loop is detected or a removed legacy package is referenced.
    """
    if manifests is None:
        manifests = discover_packages(repo_root)

    # Normalize incoming package list
    incoming_pkgs: list[str] = []
    if isinstance(packages_map, (list, set, tuple)) or hasattr(packages_map, "keys"):
        incoming_pkgs = [str(p).strip() for p in packages_map if str(p).strip()]

    # Validate against legacy packages
    all_packages: set[str] = set()
    for clean_name in incoming_pkgs:
        if clean_name in REMOVED_LEGACY_PACKAGES:
            target = REMOVED_LEGACY_PACKAGES[clean_name]
            raise ValueError(f"Package '{clean_name}' has been consolidated into '{target}'. Use '{target}' instead.")
        all_packages.add(clean_name)

    # Transitive expansion
    direct_deps_graph: dict[str, set[str]] = {}
    queue: list[str] = list(all_packages)
    visited_for_expansion: set[str] = set()

    while queue:
        current_pkg = queue.pop(0)
        if current_pkg in visited_for_expansion:
            continue
        visited_for_expansion.add(current_pkg)

        current_deps: set[str] = set()
        manifest = manifests.get(current_pkg)
        if manifest is not None:
            current_deps.update(manifest.runtime.dependencies)
            if include_build_packages:
                current_deps.update(manifest.payload.build_packages)

        direct_deps_graph[current_pkg] = current_deps

        for dep in current_deps:
            if dep in REMOVED_LEGACY_PACKAGES:
                target = REMOVED_LEGACY_PACKAGES[dep]
                raise ValueError(f"Package '{dep}' has been consolidated into '{target}'. Use '{target}' instead.")
            if dep not in all_packages:
                all_packages.add(dep)
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

    for pkg in sorted(all_packages):
        if pkg not in visited:
            _dfs(pkg, [])

    return {pkg: [] for pkg in sorted_order}
