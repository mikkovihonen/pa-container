from __future__ import annotations

import importlib.util
import sys
from types import ModuleType
from typing import TYPE_CHECKING, Any

from packages.discovery import get_package_dir
from packages.plugin import ACPPlugin

if TYPE_CHECKING:
    from pathlib import Path

    from packages.manifest import PackageManifest

sys.dont_write_bytecode = True


def _ensure_parent_modules(module_name: str, package_dir: Path) -> None:
    """Ensure parent package modules exist in sys.modules with proper __path__ for relative imports."""
    parts = module_name.split(".")
    for i in range(1, len(parts)):
        parent_name = ".".join(parts[:i])
        if parent_name not in sys.modules:
            parent_mod = ModuleType(parent_name)
            if i == 1:
                parent_mod.__path__ = []
            elif i == 2:
                parent_mod.__path__ = [str(package_dir)]
            else:
                rel_parts = parts[2:i]
                sub_dir = package_dir.joinpath(*rel_parts)
                parent_mod.__path__ = [str(sub_dir)] if sub_dir.is_dir() else []
            parent_mod.__package__ = parent_name
            sys.modules[parent_name] = parent_mod


def load_acp_plugin(
    manifest: PackageManifest,
    package_dir: Path,
    project_dir: Path | None = None,
) -> ACPPlugin | None:
    """Dynamically load an ACPPlugin from packages/<pkg>/host/.

    Args:
        manifest: Loaded PackageManifest for the ACP.
        package_dir: Absolute path to the ACP directory (e.g. packages/<name>).
        project_dir: Active project directory, or None if outside a project.

    Returns:
        Instantiated ACPPlugin, or None if no entrypoint is declared.

    Raises:
        FileNotFoundError: If declared host entrypoint file does not exist.
        ImportError: If importlib cannot create or execute the module specification.
        AttributeError: If plugin class is not exported by the module.
        TypeError: If plugin class is not a subclass of ACPPlugin.
    """
    entrypoint = manifest.extension.entrypoint
    if not entrypoint or not entrypoint.strip():
        return None

    if ":" not in entrypoint:
        raise ValueError(f"ACP '{manifest.name}': entrypoint must be in 'module:ClassName' format, got '{entrypoint}'")

    module_relpath, class_name = entrypoint.strip().split(":", 1)
    module_relpath = module_relpath.strip()
    class_name = class_name.strip()

    # Resolves e.g. "host.plugin" -> packages/<name>/host/plugin.py
    module_path = package_dir / (module_relpath.replace(".", "/") + ".py")
    if not module_path.is_file():
        raise FileNotFoundError(f"ACP '{manifest.name}': declared host entrypoint file not found: {module_path}")

    safe_pkg_name = manifest.name.replace("-", "_")
    module_name = f"pa_packages.{safe_pkg_name}.{module_relpath}"
    mod: ModuleType
    if module_name not in sys.modules:
        _ensure_parent_modules(module_name, package_dir)
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load spec for module '{module_name}' at {module_path}")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = mod
        spec.loader.exec_module(mod)
    else:
        mod = sys.modules[module_name]

    plugin_cls_obj = getattr(mod, class_name, None)
    if plugin_cls_obj is None:
        raise AttributeError(f"ACP '{manifest.name}': class '{class_name}' not found in {module_path}")

    if not isinstance(plugin_cls_obj, type) or not issubclass(plugin_cls_obj, ACPPlugin):
        raise TypeError(f"ACP '{manifest.name}': '{class_name}' must be a subclass of ACPPlugin")

    plugin_cls = plugin_cls_obj
    return plugin_cls(manifest=manifest, package_dir=package_dir, project_dir=project_dir)


def load_active_plugins(
    manifests: dict[str, PackageManifest],
    packages_dir: Path,
    project_dir: Path | None,
) -> dict[str, ACPPlugin]:
    """Load all ACP plugins for the provided package manifests.

    Args:
        manifests: Mapping of package name to PackageManifest.
        packages_dir: Root directory containing package definitions (REPO_ROOT / 'packages').
        project_dir: Active project directory, or None if running globally.

    Returns:
        Mapping of package name to active ACPPlugin instances.
    """
    plugins: dict[str, ACPPlugin] = {}
    for name, manifest in manifests.items():
        pkg_dir = packages_dir / name
        plugin = load_acp_plugin(manifest=manifest, package_dir=pkg_dir, project_dir=project_dir)
        if plugin is not None:
            plugins[name] = plugin
    return plugins


def load_project_plugins(
    project_dir: Path | None,
    extra_packages: list[str] | None = None,
    repo_root: Path | None = None,
) -> dict[str, ACPPlugin]:
    """Load all ACP plugins active for the specified project directory.

    Args:
        project_dir: Active project directory, or None.
        extra_packages: Optional list of additional package names to activate.
        repo_root: Optional root of repository containing packages/.

    Returns:
        Mapping of package name to active ACPPlugin instances.
    """
    from images import read_project_packages
    from packages.discovery import discover_packages, get_packages_dir

    if project_dir is not None:
        active_pkgs = read_project_packages(project_dir, extra_packages=extra_packages)
    else:
        active_pkgs = list(extra_packages or [])
    manifests = discover_packages(repo_root)
    packages_dir = get_packages_dir(repo_root)
    active_manifests = {p: manifests[p] for p in active_pkgs if p in manifests}
    return load_active_plugins(active_manifests, packages_dir=packages_dir, project_dir=project_dir)


def get_package_host_module(package_name: str, module_name: str, packages_dir: Path | None = None) -> Any:
    """Load an ACP package and return a specific host module (e.g. ('virtual-desktop', 'desktop'))."""
    from packages.discovery import discover_packages

    manifests = discover_packages(packages_dir)
    if package_name not in manifests:
        raise ValueError(f"Package '{package_name}' not found")
    manifest = manifests[package_name]
    repo_root = packages_dir.parent if packages_dir else None
    pkg_dir = get_package_dir(manifest.name, repo_root=repo_root)
    load_acp_plugin(manifest, pkg_dir)
    safe_pkg_name = manifest.name.replace("-", "_")
    mod_key = f"pa_packages.{safe_pkg_name}.host.{module_name}"
    if mod_key in sys.modules:
        return sys.modules[mod_key]
    return importlib.import_module(mod_key)
