from __future__ import annotations

import argparse
from typing import TYPE_CHECKING

import pytest
from pa_packages.agents.host.base import AgentDriver
from pa_packages.agents.host.plugin import AgentsPlugin

from packages.plugin import ContainerRunSpec, RunContext

if TYPE_CHECKING:
    from pathlib import Path

    from packages.manifest import PackageManifest


@pytest.fixture
def dummy_manifest() -> PackageManifest:
    import yaml

    manifest_yaml = """
schema_version: "3.0.0"
name: "agents"
version: "1.0.0"
description: "Unified AI coding agents runtime capability"
category: "agents"
license: "MIT"
features:
    pi:
        description: "Native Pi coding agent"
        default: true
    claude:
        description: "Claude Code"
        default: false
    opencode:
        description: "OpenCode"
        default: false
    antigravity:
        description: "Antigravity"
        default: false
"""
    from packages.manifest import parse_package_manifest

    return parse_package_manifest(yaml.safe_load(manifest_yaml))


def test_agents_plugin_schema(dummy_manifest: PackageManifest, tmp_path: Path):
    plugin = AgentsPlugin(dummy_manifest, tmp_path / "agents", tmp_path)
    schema = plugin.contribute_config_schema()
    assert isinstance(schema, dict)
    assert "default" in schema["keys"]
    assert "mounts" in schema["keys"]
    assert "env" in schema["keys"]


def test_agents_plugin_secret_mappings(dummy_manifest: PackageManifest, tmp_path: Path):
    plugin = AgentsPlugin(dummy_manifest, tmp_path / "agents", tmp_path)

    # Empty/default config (only pi enabled) -> no external API secrets required
    mappings_pi = plugin.get_secret_mappings(
        {"packages": [{"agents": {"features": ["pi"], "config": {}, "secrets": []}}]}
    )
    assert len(mappings_pi) == 0

    # Claude enabled with explicit secret -> Anthropic API key mapping contributed
    mappings_claude = plugin.get_secret_mappings(
        {
            "packages": [
                {
                    "agents": {
                        "features": ["claude"],
                        "config": {},
                        "secrets": [{"name": "anthropic", "account": "ANTHROPIC_API_KEY"}],
                    }
                }
            ]
        }
    )
    assert len(mappings_claude) == 1
    assert mappings_claude[0].keyring_account == "ANTHROPIC_API_KEY"

    # Antigravity enabled with explicit secret -> Gemini API key mapping contributed
    mappings_agy = plugin.get_secret_mappings(
        {
            "packages": [
                {
                    "agents": {
                        "features": ["antigravity"],
                        "config": {},
                        "secrets": [{"name": "gemini", "account": "GEMINI_API_KEY"}],
                    }
                }
            ]
        }
    )
    assert len(mappings_agy) == 1
    assert mappings_agy[0].keyring_account == "GEMINI_API_KEY"

    # Both enabled with explicit secrets -> Both mappings contributed
    mappings_both = plugin.get_secret_mappings(
        {
            "packages": [
                {
                    "agents": {
                        "features": ["claude", "antigravity"],
                        "config": {},
                        "secrets": [
                            {"name": "anthropic", "account": "ANTHROPIC_API_KEY"},
                            {"name": "gemini", "account": "GEMINI_API_KEY"},
                        ],
                    }
                }
            ]
        }
    )
    assert len(mappings_both) == 2


def test_agents_plugin_lifecycle_and_configure(dummy_manifest: PackageManifest, tmp_path: Path):
    project_dir = tmp_path / "project"
    project_dir.mkdir(parents=True)
    pa_dir = project_dir / ".pa-container"
    pa_dir.mkdir(parents=True)

    config_data = {
        "packages": [
            {
                "agents": {
                    "features": ["pi", "opencode"],
                    "config": {},
                    "secrets": [],
                }
            }
        ],
        "agent": {
            "default": "pi",
        },
    }
    import yaml

    (pa_dir / "config.yaml").write_text(yaml.dump(config_data))

    plugin = AgentsPlugin(dummy_manifest, tmp_path / "agents", project_dir)
    options = argparse.Namespace(agent=None)
    ctx = RunContext(
        project_dir=project_dir,
        options=options,  # type: ignore[arg-type]
        config=config_data,
        active_packages=["agents"],
    )

    plugin.on_run_init(ctx)

    active_drv = ctx.get_attribute("agents.active_driver")
    assert isinstance(active_drv, AgentDriver)
    assert active_drv.name == "pi"

    selected_drvs = ctx.get_attribute("agents.selected_drivers")
    assert len(selected_drvs) == 1
    assert selected_drvs[0].name == "pi"

    spec = ContainerRunSpec()
    plugin.on_container_configure(spec, ctx)

    assert spec.env["PA_CONTAINER_AGENT"] == "pi"
    assert spec.env["PA_CONTAINER_ENABLED_AGENTS"] == "pi"
    assert spec.env["PA_AGENT_SKILLS_DIRS"] == "/home/agent/.pi/agent/skills"
    assert any(m.destination == "/home/agent/.pi/agent" for m in spec.mounts)
    assert "/home/agent/.pi/agent/bin" in spec.chown_paths
