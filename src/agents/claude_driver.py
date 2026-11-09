from __future__ import annotations

import json
import os
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from config_types import AgentExtrasConfig, GatewayConfigItem, ServerConfigItem

sys.dont_write_bytecode = True

from agents.base import AgentDriver, AgentMount, T3DriverMetadata
from logging_driver import LogCategory, get_category_logger

logger = get_category_logger(__name__, LogCategory.AGENT)

"""Runtime driver for Anthropic Claude Code (@anthropic-ai/claude-code)."""


class ClaudeDriver(AgentDriver):
    """Driver for Anthropic Claude Code."""

    @property
    def name(self) -> str:
        return "claude"

    @property
    def required_tools(self) -> list[str]:
        return ["claude-code"]

    def get_command(self, cli_args: list[str]) -> list[str]:
        return cli_args

    def get_environment(
        self,
        config: AgentExtrasConfig | None = None,
        gateway_configs: list[GatewayConfigItem] | None = None,
    ) -> dict[str, str]:
        is_agent_native = False
        if gateway_configs:
            for gw in gateway_configs:
                gw_def = gw.get("gatewayDef")
                name = gw.get("name") or (gw_def and gw_def.id)
                auth = gw_def.auth if gw_def else None
                if name == "anthropic-account" or (
                    (gw_def and gw_def.gateway_type == "anthropic") and auth and auth.type == "agent-native"
                ):
                    is_agent_native = True
                    break

        env: dict[str, str] = {
            "CLAUDE_CONFIG_DIR": "/home/agent/.claude",
        }
        if not is_agent_native:
            env["ANTHROPIC_API_KEY"] = "ANTHROPIC_API_KEY_PLACEHOLDER"
        else:
            if "CLAUDE_CODE_OAUTH_TOKEN" in os.environ:
                env["CLAUDE_CODE_OAUTH_TOKEN"] = os.environ["CLAUDE_CODE_OAUTH_TOKEN"]
            elif config and config.get("env") and "CLAUDE_CODE_OAUTH_TOKEN" in config["env"]:
                env["CLAUDE_CODE_OAUTH_TOKEN"] = str(config["env"]["CLAUDE_CODE_OAUTH_TOKEN"])

        if config and config.get("env") and "ANTHROPIC_BASE_URL" in config["env"]:
            env["ANTHROPIC_BASE_URL"] = str(config["env"]["ANTHROPIC_BASE_URL"])
        return env

    def get_mounts(self, project_dir: Path) -> list[AgentMount]:
        claude_dir = self.get_state_dir(project_dir)
        claude_dir.mkdir(parents=True, exist_ok=True)
        return [
            AgentMount(source=claude_dir, destination="/home/agent/.claude"),
        ]

    def synthesize_config(
        self,
        server_configs: list[ServerConfigItem],
        gateway_configs: list[GatewayConfigItem],
        default_model: str | None,
        project_dir: Path,
    ) -> None:
        """Synthesize Claude Code configuration in state_dir."""
        claude_dir = self.get_state_dir(project_dir)
        claude_dir.mkdir(parents=True, exist_ok=True)
        config_file = claude_dir / "claude.json"
        settings_file = claude_dir / "settings.json"

        # Claude Code connects to Anthropic Messages API.
        # It cannot connect to local llama-server (OpenAI-compatible) instances.
        anthropic_gw = next(
            (
                gw
                for gw in gateway_configs
                if (gw.get("gatewayDef") and getattr(gw["gatewayDef"], "gateway_type", None) == "anthropic")
                or (
                    gw.get("gatewayDef") and getattr(gw["gatewayDef"], "id", None) in ("anthropic", "anthropic-account")
                )
                or gw.get("name") in ("anthropic", "anthropic-account")
            ),
            None,
        )

        base_url: str | None = None
        if anthropic_gw is not None:
            raw_url = (
                anthropic_gw.get("baseUrl")
                or (anthropic_gw.get("gatewayDef") and getattr(anthropic_gw["gatewayDef"], "base_url", None))
                or ""
            )
            clean_url = raw_url.rstrip("/")
            # Claude Code appends /v1/messages to ANTHROPIC_BASE_URL.
            # If the gateway URL ends with /v1, strip it so requests do not hit /v1/v1/messages.
            if clean_url.endswith("/v1"):
                clean_url = clean_url[:-3]
            # Standard public Anthropic API endpoint does not need custom base URL
            if clean_url and clean_url != "https://api.anthropic.com":
                base_url = clean_url
        else:
            logger.warning(
                "Claude Code agent synthesized without an Anthropic gateway in models.yaml. "
                "API requests will fail unless an 'anthropic' or 'anthropic-account' gateway is configured."
            )

        # Determine model name
        if default_model and (
            default_model.startswith("claude-")
            or (anthropic_gw is not None and default_model == anthropic_gw.get("name"))
        ):
            model_name = default_model
        else:
            model_name = "claude-sonnet-5-5"

        config_data: dict[str, str] = {
            "model": model_name,
        }
        if base_url:
            config_data["baseUrl"] = base_url

        with config_file.open("w") as f:
            json.dump(config_data, f, indent=2)

        settings_data: dict[str, object] = {
            "model": model_name,
        }
        if base_url:
            settings_data["env"] = {"ANTHROPIC_BASE_URL": base_url}

        with settings_file.open("w") as f:
            json.dump(settings_data, f, indent=2)

    def get_t3_metadata(self) -> T3DriverMetadata:
        return T3DriverMetadata(
            driver_kind="claudeAgent",
            instance_id="claudeAgent",
            settings={"binaryPath": "claude", "homePath": "/home/agent/.claude", "launchArgs": ""},
        )
