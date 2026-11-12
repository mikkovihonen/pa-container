from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from config_types import GatewayConfigItem, ServerConfigItem

sys.dont_write_bytecode = True

from ..base import AgentDriver, AgentMount, OrchestratorProviderMetadata

"""Runtime driver for the Pi coding agent (@earendil-works/pi-coding-agent)."""


class PiAgentDriver(AgentDriver):
    """Driver for the native Pi coding agent."""

    @property
    def name(self) -> str:
        return "pi"

    @property
    def required_packages(self) -> list[str]:
        return ["agents"]

    def get_command(self, cli_args: list[str]) -> list[str]:
        if cli_args and cli_args[0] == "pi":
            return cli_args
        return ["pi", *cli_args]

    def get_mounts(self, project_dir: Path) -> list[AgentMount]:
        state_dir = self.get_state_dir(project_dir)
        state_dir.mkdir(parents=True, exist_ok=True)
        return [
            AgentMount(source=state_dir, destination="/home/agent/.pi/agent"),
        ]

    def get_shadow_paths(self) -> list[str]:
        return ["/home/agent/.pi/agent/bin"]

    def get_skills_path(self) -> str | None:
        return ".pi/agent/skills"

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
            gw_def = gw.get("gatewayDef")
            base_url = gw.get("baseUrl") or (gw_def and gw_def.base_url) or ""

            gw_models: list[dict[str, object]] = []
            if gw.get("models"):
                for m in gw["models"]:
                    if isinstance(m, dict) and m.get("id"):
                        gw_models.append(dict(m))
                    elif isinstance(m, str) and m.strip():
                        gw_models.append({"id": m.strip(), "name": m.strip()})

            if not gw_models:
                gw_models = [{"id": name, "name": name}]

            providers[name] = {
                "baseUrl": base_url,
                "api": "openai-completions",
                "apiKey": f"{name.upper().replace('-', '_')}_API_KEY_PLACEHOLDER",
                "models": gw_models,
            }

        with models_json_path.open("w") as f:
            json.dump({"providers": providers}, f, indent=2)

        # Clear any empty-string API keys in auth.json that could shadow models.json placeholders
        auth_json_path = state_dir / "auth.json"
        if auth_json_path.is_file():
            try:
                auth_data = json.loads(auth_json_path.read_text())
                if isinstance(auth_data, dict):
                    modified = False
                    for gw in gateway_configs:
                        gw_name = gw["name"]
                        if (
                            gw_name in auth_data
                            and isinstance(auth_data[gw_name], dict)
                            and not auth_data[gw_name].get("key")
                        ):
                            del auth_data[gw_name]
                            modified = True
                    if modified:
                        auth_json_path.write_text(json.dumps(auth_data, indent=2))
            except Exception:
                pass

    def get_orchestrator_metadata(self, orchestrator: str) -> OrchestratorProviderMetadata | None:
        if orchestrator == "t3":
            return OrchestratorProviderMetadata(
                provider_kind="pi",
                instance_id="pi",
                settings={"binaryPath": "pi", "launchArgs": ""},
            )
        return None
