from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

sys.dont_write_bytecode = True

from packages.loader import load_acp_plugin, load_active_plugins
from packages.manifest import ExtensionConfig, PackageManifest
from packages.plugin import ACPPlugin


class SampleTestPlugin(ACPPlugin):
    def contribute_config_schema(self) -> type[object] | None:
        return dict


def _make_dummy_manifest(name: str, entrypoint: str | None = None) -> PackageManifest:
    return PackageManifest(
        schema_version="3.0.0",
        name=name,
        version="1.0.0",
        extension=ExtensionConfig(entrypoint=entrypoint),
    )


def test_load_acp_plugin_none_entrypoint(tmp_path: Path) -> None:
    manifest = _make_dummy_manifest("test-none", None)
    plugin = load_acp_plugin(manifest, tmp_path, tmp_path)
    assert plugin is None


def test_load_acp_plugin_invalid_format(tmp_path: Path) -> None:
    manifest = _make_dummy_manifest("test-bad", "no_colon_here")
    with pytest.raises(ValueError, match="entrypoint must be in 'module:ClassName' format"):
        load_acp_plugin(manifest, tmp_path, tmp_path)


def test_load_acp_plugin_file_not_found(tmp_path: Path) -> None:
    manifest = _make_dummy_manifest("test-missing", "host.plugin:MyPlugin")
    with pytest.raises(FileNotFoundError, match="declared host entrypoint file not found"):
        load_acp_plugin(manifest, tmp_path, tmp_path)


def test_load_acp_plugin_success(tmp_path: Path) -> None:
    host_dir = tmp_path / "host"
    host_dir.mkdir(parents=True)
    plugin_py = host_dir / "plugin.py"
    plugin_py.write_text(
        """
from packages.plugin import ACPPlugin

class ConcreteTestPlugin(ACPPlugin):
    pass
"""
    )
    manifest = _make_dummy_manifest("test-good", "host.plugin:ConcreteTestPlugin")
    plugin = load_acp_plugin(manifest, tmp_path, tmp_path)
    assert plugin is not None
    assert plugin.manifest.name == "test-good"
    assert isinstance(plugin, ACPPlugin)


def test_load_acp_plugin_wrong_subclass(tmp_path: Path) -> None:
    host_dir = tmp_path / "host"
    host_dir.mkdir(parents=True)
    plugin_py = host_dir / "plugin.py"
    plugin_py.write_text(
        """
class NotAPlugin:
    pass
"""
    )
    manifest = _make_dummy_manifest("test-wrong-type", "host.plugin:NotAPlugin")
    with pytest.raises(TypeError, match="must be a subclass of ACPPlugin"):
        load_acp_plugin(manifest, tmp_path, tmp_path)


def test_load_acp_plugin_class_not_found(tmp_path: Path) -> None:
    host_dir = tmp_path / "host"
    host_dir.mkdir(parents=True)
    plugin_py = host_dir / "plugin.py"
    plugin_py.write_text("class OtherClass: pass\n")
    manifest = _make_dummy_manifest("test-missing-class", "host.plugin:NonExistent")
    with pytest.raises(AttributeError, match="class 'NonExistent' not found"):
        load_acp_plugin(manifest, tmp_path, tmp_path)


def test_load_active_plugins(tmp_path: Path) -> None:
    pkg_dir = tmp_path / "pkg1"
    host_dir = pkg_dir / "host"
    host_dir.mkdir(parents=True)
    (host_dir / "plugin.py").write_text(
        """
from packages.plugin import ACPPlugin
class P1(ACPPlugin): pass
"""
    )
    manifest1 = _make_dummy_manifest("pkg1", "host.plugin:P1")
    manifest2 = _make_dummy_manifest("pkg2", None)

    manifests = {"pkg1": manifest1, "pkg2": manifest2}
    plugins = load_active_plugins(manifests, tmp_path, None)
    assert len(plugins) == 1
    assert "pkg1" in plugins
    assert isinstance(plugins["pkg1"], ACPPlugin)
