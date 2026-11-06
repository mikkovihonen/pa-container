from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

sys.dont_write_bytecode = True

from agents.base import AgentDriver, AgentMount

"""Runtime driver for the Antigravity agent (Google Antigravity CLI / AGY)."""


class AntigravityDriver(AgentDriver):
    """Driver for the Google Antigravity agent."""

    @property
    def name(self) -> str:
        return "antigravity"

    @property
    def required_tools(self) -> list[str]:
        return ["antigravity"]

    def get_command(self, cli_args: list[str]) -> list[str]:
        return cli_args

    def get_environment(self, config: dict | None = None) -> dict[str, str]:
        return {
            "GEMINI_API_KEY": "pi-container-token-placeholder",
        }

    def get_mounts(self, project_dir: Path, agent_config_dir: Path) -> list[AgentMount]:
        agy_dir = project_dir / ".pi-container" / "agents" / "antigravity"
        agy_dir.mkdir(parents=True, exist_ok=True)
        return [
            AgentMount(source=agy_dir, destination="/home/pi/.gemini/antigravity"),
        ]

    def synthesize_config(
        self,
        server_configs: list[dict],
        gateway_configs: list[dict],
        default_model: str | None,
        project_dir: Path,
        agent_config_dir: Path,
    ) -> None:
        """Synthesize Antigravity model configurations."""
        agy_dir = project_dir / ".pi-container" / "agents" / "antigravity"
        agy_dir.mkdir(parents=True, exist_ok=True)
        config_file = agy_dir / "config.json"

        endpoints: list[dict] = []
        for srv in server_configs:
            name = srv["name"]
            endpoints.append(
                {
                    "name": name,
                    "endpoint": srv.get("baseUrl") or "http://llama:9999/v1",
                    "type": "llama-server",
                }
            )

        for gw in gateway_configs:
            name = gw["name"]
            base_url = gw.get("baseUrl") or (gw.get("gatewayDef") and gw["gatewayDef"].base_url) or ""
            endpoints.append(
                {
                    "name": name,
                    "endpoint": base_url,
                    "type": "gateway",
                }
            )

        config_data = {
            "defaultModel": default_model or (server_configs and server_configs[0]["name"]) or "gemini-2.5-pro",
            "models": endpoints,
        }

        with config_file.open("w") as f:
            json.dump(config_data, f, indent=2)
