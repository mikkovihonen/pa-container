from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from config_types import AgentExtrasConfig, GatewayConfigItem, ServerConfigItem

sys.dont_write_bytecode = True

from agents.base import AgentDriver, AgentMount, T3DriverMetadata
from logging_driver import LogCategory, get_category_logger

logger = get_category_logger(__name__, LogCategory.AGENT)

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

    def get_environment(
        self,
        config: AgentExtrasConfig | None = None,
        gateway_configs: list[GatewayConfigItem] | None = None,
    ) -> dict[str, str]:
        is_agent_native = False
        base_url: str | None = None
        if gateway_configs:
            for gw in gateway_configs:
                gw_def = gw.get("gatewayDef")
                name = gw.get("name") or (gw_def and getattr(gw_def, "id", None))
                auth = getattr(gw_def, "auth", None) if gw_def else None
                if name == "google-account" or (
                    (gw_def and getattr(gw_def, "gateway_type", None) == "gemini")
                    and auth
                    and getattr(auth, "type", None) == "agent-native"
                ):
                    is_agent_native = True
                if (gw_def and getattr(gw_def, "gateway_type", None) == "gemini") or name in (
                    "gemini",
                    "google-account",
                ):
                    raw_url = gw.get("baseUrl") or (gw_def and getattr(gw_def, "base_url", None)) or ""
                    clean_url = raw_url.rstrip("/")
                    if clean_url and clean_url != "https://generativelanguage.googleapis.com":
                        base_url = clean_url

        env: dict[str, str] = {}
        if not is_agent_native:
            env["GEMINI_API_KEY"] = "GEMINI_API_KEY_PLACEHOLDER"

        if base_url:
            env["GOOGLE_GEMINI_BASE_URL"] = base_url
        elif config and config.get("env") and "GOOGLE_GEMINI_BASE_URL" in config["env"]:
            env["GOOGLE_GEMINI_BASE_URL"] = str(config["env"]["GOOGLE_GEMINI_BASE_URL"])

        return env

    def get_mounts(self, project_dir: Path) -> list[AgentMount]:
        agy_dir = self.get_state_dir(project_dir)
        agy_dir.mkdir(parents=True, exist_ok=True)
        config_dir = agy_dir / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        return [
            AgentMount(source=agy_dir, destination="/home/agent/.gemini/antigravity"),
            AgentMount(source=config_dir, destination="/home/agent/.gemini/config"),
        ]

    def synthesize_config(
        self,
        server_configs: list[ServerConfigItem],
        gateway_configs: list[GatewayConfigItem],
        default_model: str | None,
        project_dir: Path,
    ) -> None:
        """Synthesize Antigravity configuration in state_dir."""
        agy_dir = self.get_state_dir(project_dir)
        agy_dir.mkdir(parents=True, exist_ok=True)
        config_file = agy_dir / "config.json"
        settings_file = agy_dir / "settings.json"

        # Google Antigravity connects to Gemini API or Google Account OAuth.
        # It cannot connect to local llama-server (OpenAI-compatible) instances.
        gemini_gw = next(
            (
                gw
                for gw in gateway_configs
                if (gw.get("gatewayDef") and getattr(gw["gatewayDef"], "gateway_type", None) == "gemini")
                or (gw.get("gatewayDef") and getattr(gw["gatewayDef"], "id", None) in ("gemini", "google-account"))
                or gw.get("name") in ("gemini", "google-account")
            ),
            None,
        )

        base_url: str | None = None
        if gemini_gw is not None:
            raw_url = (
                gemini_gw.get("baseUrl")
                or (gemini_gw.get("gatewayDef") and getattr(gemini_gw["gatewayDef"], "base_url", None))
                or ""
            )
            clean_url = raw_url.rstrip("/")
            # Standard public Gemini endpoint does not need custom base URL
            if clean_url and clean_url != "https://generativelanguage.googleapis.com":
                base_url = clean_url
        else:
            logger.warning(
                "Antigravity agent synthesized without a Gemini gateway in models.yaml. "
                "API requests will fail unless a 'gemini' or 'google-account' gateway is configured."
            )

        # Determine model name
        if default_model and (
            default_model.startswith("gemini-") or (gemini_gw is not None and default_model == gemini_gw.get("name"))
        ):
            model_name = default_model
        else:
            model_name = "gemini-2.5-pro"

        endpoints: list[dict[str, object]] = []
        if gemini_gw is not None:
            gw_name = gemini_gw.get("name") or "gemini"
            endpoints.append(
                {
                    "name": gw_name,
                    "endpoint": base_url or "https://generativelanguage.googleapis.com",
                    "type": "gateway",
                }
            )

        config_data: dict[str, object] = {
            "model": model_name,
            "defaultModel": model_name,
            "models": endpoints,
        }
        if base_url:
            config_data["baseUrl"] = base_url

        with config_file.open("w") as f:
            json.dump(config_data, f, indent=2)

        settings_data: dict[str, object] = {
            "model": model_name,
        }
        if base_url:
            settings_data["baseUrl"] = base_url
            settings_data["env"] = {"GOOGLE_GEMINI_BASE_URL": base_url}

        with settings_file.open("w") as f:
            json.dump(settings_data, f, indent=2)

    def get_t3_metadata(self) -> T3DriverMetadata:
        return T3DriverMetadata(
            driver_kind="antigravity",
            instance_id="antigravity",
            settings={"authMethod": "oauth-personal"},
        )
