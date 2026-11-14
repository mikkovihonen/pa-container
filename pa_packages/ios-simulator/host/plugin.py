from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from packages.plugin import ACPPlugin

if TYPE_CHECKING:
    from pathlib import Path

    from packages.manifest import PackageManifest

log = logging.getLogger(__name__)


class IOSSimulatorPlugin(ACPPlugin):
    """Host plugin exposing iOS Simulator ACP tools and provisioning."""

    def __init__(
        self,
        manifest: PackageManifest | None = None,
        package_dir: Path | None = None,
        project_dir: Path | None = None,
    ) -> None:
        if manifest is not None and package_dir is not None:
            super().__init__(manifest, package_dir, project_dir)

    def contribute_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "ios_build_and_install",
                "description": "Build an Xcode project/scheme and install on dedicated iOS Simulator",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "project_path": {"type": "string"},
                        "scheme": {"type": "string"},
                    },
                    "required": ["project_path", "scheme"],
                },
            },
            {
                "name": "ios_screenshot",
                "description": "Capture PNG screenshot from dedicated iOS Simulator",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "output_path": {"type": "string"},
                    },
                    "required": ["output_path"],
                },
            },
            {
                "name": "ios_tap",
                "description": "Tap at (x, y) coordinates on iOS Simulator screen",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "x": {"type": "integer"},
                        "y": {"type": "integer"},
                    },
                    "required": ["x", "y"],
                },
            },
            {
                "name": "ios_type",
                "description": "Type text into current focused element on iOS Simulator",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                    },
                    "required": ["text"],
                },
            },
            {
                "name": "ios_xctest",
                "description": "Run XCTest suite on dedicated iOS Simulator without re-building",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "scheme": {"type": "string"},
                    },
                },
            },
        ]
