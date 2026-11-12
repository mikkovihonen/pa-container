from __future__ import annotations

import copy
import importlib.abc
import importlib.machinery
import importlib.util
import sys
from types import ModuleType
from typing import TYPE_CHECKING, Any

from packages.discovery import get_package_dir
from packages.manifest import load_package_manifest
from packages.plugin import ACPPlugin
from yaml_strict import load_yaml_strict

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
            parent_spec = importlib.machinery.ModuleSpec(parent_name, None, is_package=True)
            parent_spec.submodule_search_locations = parent_mod.__path__
            parent_mod.__spec__ = parent_spec
            sys.modules[parent_name] = parent_mod


def load_acp_plugin(
    manifest: PackageManifest,
    package_dir: Path,
    project_dir: Path | None = None,
) -> ACPPlugin | None:
    """Dynamically load an ACPPlugin from pa_packages/<pkg>/host/.

    Args:
        manifest: Loaded PackageManifest for the ACP.
        package_dir: Absolute path to the ACP directory (e.g. pa_packages/<name>).
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

    # Resolves e.g. "host.plugin" -> pa_packages/<name>/host/plugin.py
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
        packages_dir: Root directory containing package definitions (REPO_ROOT / 'pa_packages').
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

    manifests = discover_packages(repo_root)
    packages_dir = get_packages_dir(repo_root)

    if project_dir is not None:
        active_pkgs = read_project_packages(project_dir, extra_packages=extra_packages, include_core=True)
    else:
        active_pkgs = list(extra_packages or [])
        from packages.discovery import get_core_packages

        active_pkgs.extend(get_core_packages(repo_root))

    active_manifests = {p: manifests[p] for p in active_pkgs if p in manifests}
    return load_active_plugins(active_manifests, packages_dir=packages_dir, project_dir=project_dir)


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively deep merge override mapping into base mapping."""
    merged = copy.deepcopy(base)
    for k, v in override.items():
        if k in merged and isinstance(merged[k], dict) and isinstance(v, dict):
            merged[k] = deep_merge(merged[k], v)
        else:
            merged[k] = copy.deepcopy(v)
    return merged


def resolve_project_package_declarations(
    project_dir: Path,
    repo_root: Path | None = None,
) -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, str]]]]:
    """Resolve merged package configurations and explicit secret bindings from .pa-container/config.yaml."""
    cfg_path = project_dir / ".pa-container" / "config.yaml"
    if not cfg_path.is_file():
        return {}, {}

    try:
        raw_data = load_yaml_strict(cfg_path.read_text())
    except Exception:
        return {}, {}

    if not isinstance(raw_data, dict):
        return {}, {}

    pkgs_list = raw_data.get("packages")
    if not isinstance(pkgs_list, list):
        return {}, {}

    from packages.discovery import discover_packages

    manifests = discover_packages(repo_root)
    pkg_configs: dict[str, dict[str, Any]] = {}
    pkg_secrets: dict[str, list[dict[str, str]]] = {}

    for item in pkgs_list:
        if isinstance(item, dict) and len(item) == 1:
            pkg_name, val = next(iter(item.items()))
            if not isinstance(val, dict):
                continue
            manifest = manifests.get(pkg_name)
            defaults = copy.deepcopy(manifest.config) if manifest else {}
            overrides = val.get("config") or {}
            if isinstance(overrides, dict):
                pkg_configs[pkg_name] = deep_merge(defaults, overrides)
            else:
                pkg_configs[pkg_name] = defaults

            raw_secrets = val.get("secrets") or []
            if isinstance(raw_secrets, list):
                pkg_secrets[pkg_name] = [
                    {"name": str(s.get("name")), "account": str(s.get("account"))}
                    for s in raw_secrets
                    if isinstance(s, dict) and s.get("name") and s.get("account")
                ]
            else:
                pkg_secrets[pkg_name] = []

    return pkg_configs, pkg_secrets


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


class ACPMetaPathFinder(importlib.abc.MetaPathFinder):
    """MetaPathFinder that resolves pa_packages.<pkg_name>.host.<module> dynamically."""

    def find_spec(
        self,
        fullname: str,
        path: Any,
        target: Any = None,
    ) -> importlib.machinery.ModuleSpec | None:
        if not fullname.startswith("pa_packages"):
            return None

        if fullname == "pa_packages":
            spec = importlib.machinery.ModuleSpec("pa_packages", None, is_package=True)
            return spec

        parts = fullname.split(".")
        if len(parts) < 2:
            return None

        safe_pkg_name = parts[1]
        pkg_name = safe_pkg_name.replace("_", "-")
        try:
            pkg_dir = get_package_dir(pkg_name)
        except Exception:
            try:
                pkg_dir = get_package_dir(safe_pkg_name)
            except Exception:
                return None

        manifest_path = pkg_dir / "package.yaml"
        if not manifest_path.is_file():
            return None

        manifest = load_package_manifest(manifest_path)
        load_acp_plugin(manifest, pkg_dir)
        if fullname in sys.modules:
            mod = sys.modules[fullname]
            return getattr(mod, "__spec__", None)
        return None


if not any(isinstance(finder, ACPMetaPathFinder) for finder in sys.meta_path):
    sys.meta_path.append(ACPMetaPathFinder())
