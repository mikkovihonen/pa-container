from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents.base import AgentDriver
    from config_types import ProjectConfig

sys.dont_write_bytecode = True

from packages.plugin import ACPAgentPlugin, SecretTokenMapping

from .driver import ClaudeDriver


class ClaudePlugin(ACPAgentPlugin):
    """ACP Plugin for Anthropic Claude Code."""

    def get_agent_driver(self) -> AgentDriver:
        return ClaudeDriver()

    def get_secret_mappings(self, config: ProjectConfig) -> list[SecretTokenMapping]:
        return [
            SecretTokenMapping(
                name="Anthropic API Key",
                keyring_account="ANTHROPIC_API_KEY",
                placeholder="ANTHROPIC_API_KEY_PLACEHOLDER",
                hosts=("api.anthropic.com",),
                keyring_service="pa-container",
                header="x-api-key",
                pattern="ANTHROPIC_API_KEY_PLACEHOLDER",
                required=False,
            )
        ]
