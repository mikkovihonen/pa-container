from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents.base import AgentDriver

sys.dont_write_bytecode = True

from packages.plugin import ACPAgentPlugin

from .driver import PiAgentDriver


class PiPlugin(ACPAgentPlugin):
    """ACP Plugin for the Pi Coding Agent."""

    def get_agent_driver(self) -> AgentDriver:
        return PiAgentDriver()
