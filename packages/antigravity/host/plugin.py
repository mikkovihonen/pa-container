from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents.base import AgentDriver
    from config_types import ProjectConfig

sys.dont_write_bytecode = True

from packages.plugin import ACPAgentPlugin, SecretTokenMapping

from .driver import AntigravityDriver


class AntigravityPlugin(ACPAgentPlugin):
    """ACP Plugin for Google Antigravity CLI (agy)."""

    def get_agent_driver(self) -> AgentDriver:
        return AntigravityDriver()

    def get_secret_mappings(self, config: ProjectConfig) -> list[SecretTokenMapping]:
        return [
            SecretTokenMapping(
                name="Google Gemini API Key",
                keyring_account="GEMINI_API_KEY",
                placeholder="GEMINI_API_KEY_PLACEHOLDER",
                hosts=("generativelanguage.googleapis.com",),
                keyring_service="pa-container",
                header="x-goog-api-key",
                pattern="GEMINI_API_KEY_PLACEHOLDER",
                required=False,
            )
        ]
