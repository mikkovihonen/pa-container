"""Root pytest configuration for pa-container."""

from __future__ import annotations

import sys
from pathlib import Path

# Make pa_core/ importable
repo_root = Path(__file__).resolve().parent
src_dir = repo_root / "pa_core"
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

# Ensure default global configuration exists
_global_cfg_file = Path.home() / ".config" / "pa-container" / "config.yaml"
if not _global_cfg_file.is_file():
    try:
        from global_config import init_global_config

        init_global_config(repo_root=repo_root)
    except Exception:
        pass

# Automatically discover and register all ACP packages in pa_packages namespace for test execution
from packages.loader import load_acp_plugin
from packages.manifest import load_package_manifest

packages_dir = repo_root / "pa_packages"
if packages_dir.is_dir():
    for pkg_dir in packages_dir.iterdir():
        yaml_file = pkg_dir / "package.yaml"
        if pkg_dir.is_dir() and yaml_file.is_file():
            try:
                manifest = load_package_manifest(yaml_file)
                if manifest.extension and manifest.extension.entrypoint:
                    load_acp_plugin(manifest, pkg_dir)
            except Exception as e:
                import sys
                print(f"[conftest warning] Failed to load ACP package {pkg_dir.name}: {e}", file=sys.stderr)
