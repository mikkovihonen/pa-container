from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from config_types import AgentExtrasConfig, GatewayConfigItem, ServerConfigItem

sys.dont_write_bytecode = True

from agents.base import AgentDriver, AgentMount

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

    def get_environment(self, config: AgentExtrasConfig | None = None) -> dict[str, str]:
        env = {
            "ANTHROPIC_API_KEY": "pa-container-token-placeholder",
            "CLAUDE_CONFIG_DIR": "/home/agent/.claude",
        }
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

        model_name = default_model or "claude-3-7-sonnet"
        config_data: dict[str, str] = {
            "model": model_name,
        }

        base_url = None
        if server_configs:
            base_url = server_configs[0].get("baseUrl") or "http://llama:9999/v1"
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

    def get_t3_driver(self) -> str | None:
        return "claudeAgent"
