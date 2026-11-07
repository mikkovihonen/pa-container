from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from config_types import AgentExtrasConfig, GatewayConfigItem, ServerConfigItem

sys.dont_write_bytecode = True

from agents.base import AgentDriver, AgentMount

"""Runtime driver for the OpenCode agent."""


class OpenCodeDriver(AgentDriver):
    """Driver for the OpenCode agent."""

    @property
    def name(self) -> str:
        return "opencode"

    @property
    def required_tools(self) -> list[str]:
        return ["opencode"]

    def get_command(self, cli_args: list[str]) -> list[str]:
        return cli_args

    def get_environment(self, config: AgentExtrasConfig | None = None) -> dict[str, str]:
        return {
            "OPENAI_API_KEY": "pi-container-token-placeholder",
        }

    def get_mounts(self, project_dir: Path) -> list[AgentMount]:
        opencode_dir = self.get_state_dir(project_dir)
        opencode_dir.mkdir(parents=True, exist_ok=True)
        return [
            AgentMount(source=opencode_dir, destination="/home/agent/.config/opencode"),
        ]

    def synthesize_config(
        self,
        server_configs: list[ServerConfigItem],
        gateway_configs: list[GatewayConfigItem],
        default_model: str | None,
        project_dir: Path,
    ) -> None:
        """Synthesize ~/.config/opencode/config.json from active servers and gateways."""
        opencode_dir = self.get_state_dir(project_dir)
        opencode_dir.mkdir(parents=True, exist_ok=True)
        config_file = opencode_dir / "config.json"

        endpoints: dict[str, dict[str, object]] = {}
        for srv in server_configs:
            name = srv["name"]
            endpoints[name] = {
                "type": "openai",
                "base_url": srv.get("baseUrl") or "http://llama:9999/v1",
                "api_key": "not-required",
            }

        for gw in gateway_configs:
            name = gw["name"]
            base_url = gw.get("baseUrl") or (gw.get("gatewayDef") and gw["gatewayDef"].base_url) or ""
            endpoints[name] = {
                "type": "openai",
                "base_url": base_url,
                "api_key": "pi-container-token-placeholder",
            }

        config_data = {
            "default_model": default_model or (server_configs and server_configs[0]["name"]) or "default",
            "providers": endpoints,
        }

        with config_file.open("w") as f:
            json.dump(config_data, f, indent=2)
