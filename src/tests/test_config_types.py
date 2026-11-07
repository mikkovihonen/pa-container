from __future__ import annotations

import sys

sys.dont_write_bytecode = True

"""Tests for shared configuration, manifest, and synthesis types."""

from config_types import (
    AgentExtrasConfig,
    ClientInfo,
    GatewayConfigItem,
    LlamaConfig,
    NestedContainersConfig,
    NetworkConfig,
    PortPublishConfig,
    ProjectConfig,
    ResourceLimits,
    SecurityConfig,
    ServerConfigItem,
    SourceControlConfig,
    TokenData,
)


def test_typeddict_classes_runtime_subclass() -> None:
    for cls in (
        ClientInfo,
        TokenData,
        ServerConfigItem,
        GatewayConfigItem,
        ResourceLimits,
        LlamaConfig,
        NetworkConfig,
        PortPublishConfig,
        NestedContainersConfig,
        AgentExtrasConfig,
        SecurityConfig,
        SourceControlConfig,
        ProjectConfig,
    ):
        assert issubclass(cls, dict)


def test_client_info_instantiation() -> None:
    info: ClientInfo = {
        "pid": 12345,
        "run_id": "test-run",
        "registered_at": "2026-11-07T00:00:00Z",
        "proxy_name": "test-proxy",
        "container_name": "test-container",
        "server_id": "llama-server",
    }
    assert info["pid"] == 12345
    assert info["run_id"] == "test-run"


def test_token_data_instantiation() -> None:
    token: TokenData = {
        "access_token": "token123",
        "token_type": "Bearer",
        "refresh_token": "refresh123",
        "expires_in": 3600,
        "expires_at": 1700000000.0,
        "scope": "openid",
    }
    assert token["access_token"] == "token123"
    assert token["expires_in"] == 3600


def test_server_config_item_instantiation() -> None:
    item: ServerConfigItem = {
        "name": "local-model",
        "config": None,  # type: ignore[typeddict-item]
        "baseUrl": "http://127.0.0.1:8080/v1",
    }
    assert item["name"] == "local-model"
    assert item["baseUrl"] == "http://127.0.0.1:8080/v1"


def test_gateway_config_item_instantiation() -> None:
    item: GatewayConfigItem = {
        "name": "gateway-model",
        "gatewayDef": None,  # type: ignore[typeddict-item]
        "baseUrl": "http://127.0.0.1:9090/v1",
    }
    assert item["name"] == "gateway-model"
    assert item["baseUrl"] == "http://127.0.0.1:9090/v1"


def test_project_config_subsections() -> None:
    limits: ResourceLimits = {"memory": "4g", "cpus": 2}
    llama: LlamaConfig = {"startup_timeout": 60, "startup_attempts": 3}
    net: NetworkConfig = {"ipv6": True, "dns": "1.1.1.1"}
    ports: PortPublishConfig = {"expose": "host", "publish": [(8080, 8080)]}
    nested: NestedContainersConfig = {
        "enabled": True,
        "storage": "overlay",
        "security": "rootless",
        "ports": ports,
    }
    agent: AgentExtrasConfig = {
        "env": {"FOO": "bar"},
        "mounts": ["/tmp:/tmp"],
        "capabilities": ["NET_ADMIN"],
        "devices": ["/dev/null"],
    }
    sec: SecurityConfig = {
        "read_only_git_hooks": True,
        "blocked_mount_paths": ["/etc"],
        "blocked_ip_ranges": ["10.0.0.0/8"],
        "git_config_allowlist": ["safe.directory"],
    }
    sc: SourceControlConfig = {
        "enabled": True,
        "auto_detect_host_cli": True,
        "setup_git_credentials": True,
        "providers": {},
    }

    proj: ProjectConfig = {
        "schema_version": "1.0",
        "resources": {"default": limits},
        "llama": llama,
        "network": net,
        "nested_containers": nested,
        "agent": agent,
        "security": sec,
        "source_control": sc,
    }

    assert proj["schema_version"] == "1.0"
    assert proj["resources"]["default"]["memory"] == "4g"
    assert proj["network"]["ipv6"] is True
