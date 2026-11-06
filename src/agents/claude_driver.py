from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

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

    def get_environment(self, config: dict | None = None) -> dict[str, str]:
        return {
            "ANTHROPIC_API_KEY": "pi-container-token-placeholder",
        }

    def get_mounts(self, project_dir: Path, agent_config_dir: Path) -> list[AgentMount]:
        claude_dir = project_dir / ".pi-container" / "agents" / "claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        return [
            AgentMount(source=claude_dir, destination="/home/agent/.claude"),
        ]

    def synthesize_config(
        self,
        server_configs: list[dict],
        gateway_configs: list[dict],
        default_model: str | None,
        project_dir: Path,
        agent_config_dir: Path,
    ) -> None:
        """Synthesize ~/.claude.json configuration."""
        claude_dir = project_dir / ".pi-container" / "agents" / "claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        config_file = claude_dir / "claude.json"

        config_data: dict[str, str] = {
            "model": default_model or "claude-3-7-sonnet",
        }

        # If pointing to a local Anthropic-compatible server, specify base URL
        if server_configs:
            config_data["baseUrl"] = server_configs[0].get("baseUrl") or "http://llama:9999/v1"

        with config_file.open("w") as f:
            json.dump(config_data, f, indent=2)

    def get_t3_driver(self) -> str | None:
        return "claudeAgent"
