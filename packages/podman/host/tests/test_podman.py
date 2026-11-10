from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from pa_packages.podman.host.plugin import PodmanPlugin

from cli import RunOptions
from packages.plugin import ContainerRunSpec


def test_podman_plugin_configure(tmp_path: Path):
    pa_dir = tmp_path / ".pa-container"
    pa_dir.mkdir(parents=True)
    (pa_dir / "config.yaml").write_text("packages: ['podman']\n")

    plugin = PodmanPlugin(manifest=None, package_dir=Path("."), project_dir=tmp_path)  # type: ignore[arg-type]
    spec = ContainerRunSpec()

    with patch("volumes.ensure_nested_volume", return_value=True):
        plugin.on_container_configure(spec, {}, RunOptions())  # type: ignore[arg-type]
        assert isinstance(spec.extra_run_args, list)
