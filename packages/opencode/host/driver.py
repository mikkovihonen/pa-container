from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from config_types import AgentExtrasConfig, GatewayConfigItem, ServerConfigItem

sys.dont_write_bytecode = True

from agents.base import AgentDriver, AgentMount, OrchestratorProviderMetadata

"""Runtime driver for the OpenCode agent."""


class OpenCodeDriver(AgentDriver):
    """Driver for the OpenCode agent."""

    @property
    def name(self) -> str:
        return "opencode"

    @property
    def required_packages(self) -> list[str]:
        return ["opencode"]

    def get_command(self, cli_args: list[str]) -> list[str]:
        return cli_args

    def get_environment(
        self,
        config: AgentExtrasConfig | None = None,
        gateway_configs: list[GatewayConfigItem] | None = None,
    ) -> dict[str, str]:
        return {}

    def get_mounts(self, project_dir: Path) -> list[AgentMount]:
        opencode_dir = self.get_state_dir(project_dir)
        opencode_dir.mkdir(parents=True, exist_ok=True)
        data_dir = opencode_dir / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        return [
            AgentMount(source=opencode_dir, destination="/home/agent/.config/opencode"),
            AgentMount(source=data_dir, destination="/home/agent/.local/share/opencode"),
        ]

    def get_sessions_dir(self, project_dir: Path) -> Path | None:
        return self.get_state_dir(project_dir) / "data"

    def synthesize_config(
        self,
        server_configs: list[ServerConfigItem],
        gateway_configs: list[GatewayConfigItem],
        default_model: str | None,
        project_dir: Path,
    ) -> None:
        """Synthesize ~/.config/opencode/opencode.json from active servers and gateways."""
        opencode_dir = self.get_state_dir(project_dir)
        opencode_dir.mkdir(parents=True, exist_ok=True)
        config_file = opencode_dir / "opencode.json"

        providers: dict[str, dict[str, object]] = {}
        for srv in server_configs:
            name = srv["name"]
            base_url = srv.get("baseUrl") or "http://llama:9999/v1"
            providers[name] = {
                "name": name,
                "package": "@opencode/ai/providers/openai-compatible",
                "settings": {
                    "baseURL": base_url,
                },
                "models": {
                    name: {
                        "name": name,
                    }
                },
            }

        for gw in gateway_configs:
            if not self.is_gateway_enabled_for_agent(gw):
                continue
            name = gw["name"]
            base_url = gw.get("baseUrl") or (gw.get("gatewayDef") and gw["gatewayDef"].base_url) or ""
            gw_entry: dict[str, object] = {
                "name": name,
                "package": "@opencode/ai/providers/openai-compatible",
                "settings": {
                    "baseURL": base_url,
                },
                "models": {
                    name: {
                        "name": name,
                    }
                },
            }
            if gw.get("containerEnvVar"):
                gw_entry["env"] = [gw["containerEnvVar"]]
            providers[name] = gw_entry

        valid_gws = [gw for gw in gateway_configs if self.is_gateway_enabled_for_agent(gw)]

        if default_model:
            if "/" in default_model:
                model_str = default_model
            elif default_model in providers:
                model_str = f"{default_model}/{default_model}"
            else:
                matched_prov = None
                for p_id, p_conf in providers.items():
                    models_obj = p_conf.get("models")
                    if isinstance(models_obj, dict) and default_model in models_obj:
                        matched_prov = p_id
                        break
                if matched_prov:
                    model_str = f"{matched_prov}/{default_model}"
                elif providers:
                    first_prov = next(iter(providers.keys()))
                    model_str = f"{first_prov}/{default_model}"
                else:
                    model_str = f"default/{default_model}"
        elif server_configs:
            srv_name = server_configs[0]["name"]
            model_str = f"{srv_name}/{srv_name}"
        elif valid_gws:
            gw_name = valid_gws[0]["name"]
            model_str = f"{gw_name}/{gw_name}"
        else:
            model_str = "default/default"

        config_data: dict[str, object] = {
            "$schema": "https://opencode.ai/config.json",
            "model": model_str,
            "enabled_providers": list(providers.keys()),
            "providers": providers,
        }
        mcp_servers = self.get_package_mcp_servers(project_dir)
        if mcp_servers:
            config_data["mcpServers"] = mcp_servers

        with config_file.open("w") as f:
            json.dump(config_data, f, indent=2)

    def get_orchestrator_metadata(self, orchestrator: str) -> OrchestratorProviderMetadata | None:
        if orchestrator == "t3":
            return OrchestratorProviderMetadata(
                provider_kind="opencode",
                instance_id="opencode",
                settings={"binaryPath": "opencode", "serverUrl": "", "serverPassword": ""},
            )
        return None
