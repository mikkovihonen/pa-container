from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from config_types import AgentExtrasConfig, GatewayConfigItem, ServerConfigItem

sys.dont_write_bytecode = True

from ..base import AgentDriver, AgentMount, OrchestratorProviderMetadata

"""Runtime driver for the OpenCode agent."""


class OpenCodeDriver(AgentDriver):
    """Driver for the OpenCode agent."""

    @property
    def name(self) -> str:
        return "opencode"

    @property
    def required_packages(self) -> list[str]:
        return ["agents"]

    def get_command(self, cli_args: list[str]) -> list[str]:
        if cli_args and cli_args[0] == "opencode":
            return cli_args
        return ["opencode", *cli_args]

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

    def get_skills_path(self) -> str | None:
        return ".config/opencode/skills"

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
            gw_models_dict: dict[str, object] = {}
            if gw.get("models"):
                for m in gw["models"]:
                    mid = str(m.get("id") or m.get("name"))
                    mname = str(m.get("name") or mid)
                    gw_models_dict[mid] = {"name": mname}
            if not gw_models_dict:
                gw_models_dict[name] = {"name": name}

            gw_entry: dict[str, object] = {
                "name": name,
                "package": "@opencode/ai/providers/openai-compatible",
                "settings": {
                    "baseURL": base_url,
                },
                "models": gw_models_dict,
            }
            if gw.get("containerEnvVar"):
                gw_entry["env"] = [gw["containerEnvVar"]]
            providers[name] = gw_entry

        mcp_servers = self.get_package_mcp_servers(project_dir)
        mcp_config: dict[str, object] = {}
        for s_name, s_data in mcp_servers.items():
            mcp_config[s_name] = {
                "type": s_data.get("transport", "stdio"),
                "command": [s_data["command"], *s_data.get("args", [])],
                "environment": s_data.get("env", {}),
            }

        full_config = {
            "$schema": "https://opencode.ai/config.json",
            "provider": providers,
            "mcp": mcp_config,
        }
        if default_model and default_model in providers:
            full_config["model"] = f"{default_model}/{default_model}"

        with config_file.open("w") as f:
            json.dump(full_config, f, indent=2)

    def get_orchestrator_metadata(self, orchestrator: str) -> OrchestratorProviderMetadata | None:
        if orchestrator == "t3":
            return OrchestratorProviderMetadata(
                provider_kind="opencode",
                instance_id="opencode",
                settings={"binaryPath": "opencode", "launchArgs": ""},
            )
        return None
