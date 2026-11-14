from __future__ import annotations

from factory_schema import (
    AgentSpec,
    load_factory_config,
    resolve_agent_ports,
)


def test_load_default_factory_config(tmp_path):
    cfg = load_factory_config(tmp_path / "nonexistent.toml")
    assert cfg.schema_version == "2.0"
    assert len(cfg.agents) == 1
    assert cfg.agents[0].id == "agent1"
    assert cfg.agents[0].proxy_port == 8081
    assert cfg.agents[0].transparent_port == 8091


def test_load_factory_toml(tmp_path):
    toml_content = """schema_version = "2.0"

[factory]
name = "test-factory"
description = "Multi-agent factory test"

[compute]
backend = "macos-tart"
cpus = 4
memory_mb = 8192
gpu = "required"

[capabilities]
installed = ["ios-simulator", "image-tools"]

[inference.llama_server]
enabled = true
model = "test-model.gguf"
ctx_size = 16384
gpu_layers = "all"

[ui]
t3_code = true
virtual_desktop = "wayland"

[[agents]]
id = "lead-dev"
driver = "claude"
uid = 2001
proxy_port = 8081
transparent_port = 8091
branch_prefix = "pa/lead"
allowlist = ["api.anthropic.com", "github.com"]
tokens = ["ANTHROPIC_API_KEY"]

[[agents]]
id = "qa-bot"
driver = "pi"
uid = 2002
proxy_port = 8082
transparent_port = 8092
branch_prefix = "pa/qa"
allowlist = ["pypi.org"]
tokens = ["OPENAI_API_KEY"]
"""
    f = tmp_path / "factory.toml"
    f.write_text(toml_content)

    cfg = load_factory_config(f)
    assert cfg.factory.name == "test-factory"
    assert cfg.compute.backend == "macos-tart"
    assert cfg.compute.cpus == 4
    assert cfg.compute.memory_mb == 8192
    assert cfg.capabilities.installed == ["ios-simulator", "image-tools"]
    assert cfg.inference.llama_server.enabled is True
    assert len(cfg.agents) == 2

    agent1, agent2 = cfg.agents
    assert agent1.id == "lead-dev"
    assert agent1.proxy_port == 8081
    assert agent2.id == "qa-bot"
    assert agent2.proxy_port == 8082


def test_resolve_agent_ports_explicit():
    agents = [
        AgentSpec(id="a1", proxy_port=8085, transparent_port=8095),
        AgentSpec(id="a2", proxy_port=8086, transparent_port=8096),
    ]
    resolved = resolve_agent_ports(agents, dynamic=False)
    assert resolved[0].proxy_port == 8085
    assert resolved[0].transparent_port == 8095
    assert resolved[1].proxy_port == 8086
    assert resolved[1].transparent_port == 8096


def test_resolve_agent_ports_uid_offset():
    agents = [
        AgentSpec(id="a1", uid=2001),
        AgentSpec(id="a2", uid=2002),
    ]
    resolved = resolve_agent_ports(agents, dynamic=False)
    assert resolved[0].proxy_port == 8081
    assert resolved[0].transparent_port == 8091
    assert resolved[1].proxy_port == 8082
    assert resolved[1].transparent_port == 8092


def test_resolve_agent_ports_dynamic():
    agents = [
        AgentSpec(id="a1"),
        AgentSpec(id="a2"),
    ]
    resolved = resolve_agent_ports(agents, dynamic=True)
    assert resolved[0].proxy_port is not None
    assert resolved[1].proxy_port is not None
    assert resolved[0].proxy_port != resolved[1].proxy_port
    assert resolved[0].transparent_port != resolved[1].transparent_port
