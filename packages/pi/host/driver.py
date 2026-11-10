from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from config_types import GatewayConfigItem, ServerConfigItem

sys.dont_write_bytecode = True

from agents.base import AgentDriver, AgentMount, T3DriverMetadata

"""Runtime driver for the Pi coding agent (@earendil-works/pi-coding-agent)."""


class PiAgentDriver(AgentDriver):
    """Driver for the native Pi coding agent."""

    @property
    def name(self) -> str:
        return "pi"

    @property
    def required_packages(self) -> list[str]:
        return ["pi"]

    def get_command(self, cli_args: list[str]) -> list[str]:
        return cli_args

    def get_mounts(self, project_dir: Path) -> list[AgentMount]:
        state_dir = self.get_state_dir(project_dir)
        state_dir.mkdir(parents=True, exist_ok=True)
        return [
            AgentMount(source=state_dir, destination="/home/agent/.pi/agent"),
        ]

    def get_shadow_paths(self) -> list[str]:
        return ["/home/agent/.pi/agent/bin"]

    def synthesize_config(
        self,
        server_configs: list[ServerConfigItem],
        gateway_configs: list[GatewayConfigItem],
        default_model: str | None,
        project_dir: Path,
    ) -> None:
        """Synthesize models.json in state_dir for the Pi agent container."""
        state_dir = self.get_state_dir(project_dir)
        state_dir.mkdir(parents=True, exist_ok=True)
        models_json_path = state_dir / "models.json"
        providers: dict[str, dict[str, object]] = {}
        for srv in server_configs:
            name = srv["name"]
            base_url = srv.get("baseUrl") or "http://llama:9999/v1"
            providers[name] = {
                "baseUrl": base_url,
                "api": "openai-completions",
                "apiKey": "not-required",
                "models": [{"id": name, "name": name}],
            }

        for gw in gateway_configs:
            if not self.is_gateway_enabled_for_agent(gw):
                continue
            name = gw["name"]
            base_url = gw.get("baseUrl") or (gw.get("gatewayDef") and gw["gatewayDef"].base_url) or ""
            providers[name] = {
                "baseUrl": base_url,
                "api": "openai-completions",
                "apiKey": f"{name.upper().replace('-', '_')}_API_KEY_PLACEHOLDER",
            }

        with models_json_path.open("w") as f:
            json.dump({"providers": providers}, f, indent=2)

    def get_t3_metadata(self) -> T3DriverMetadata:
        return T3DriverMetadata(
            driver_kind="pi",
            instance_id="pi",
            settings={"binaryPath": "pi", "launchArgs": ""},
        )
