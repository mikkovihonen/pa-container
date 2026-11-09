from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

    from agents.base import AgentDriver

sys.dont_write_bytecode = True

"""T3 Code configuration and policy synthesis for coding agents."""


def synthesize_t3_settings(
    t3_dir: Path,
    active_driver: AgentDriver,
    enabled_drivers: list[AgentDriver],
) -> Path:
    """Synthesize or update T3 Code userdata settings.json for active and enabled agents."""
    userdata_dir = t3_dir / "userdata"
    userdata_dir.mkdir(parents=True, exist_ok=True)
    settings_file = userdata_dir / "settings.json"

    settings: dict[str, Any] = {}
    if settings_file.is_file():
        try:
            settings = json.loads(settings_file.read_text())
            if not isinstance(settings, dict):
                settings = {}
        except Exception:
            settings = {}

    provider_instances: dict[str, Any] = settings.setdefault("providerInstances", {})

    selected_instance_ids: set[str] = set()
    for driver in enabled_drivers:
        meta = driver.get_t3_metadata()
        if meta is None:
            continue
        selected_instance_ids.add(meta.instance_id)
        existing = provider_instances.get(meta.instance_id, {})
        if not isinstance(existing, dict):
            existing = {}
        provider_instances[meta.instance_id] = {
            **existing,
            "driver": meta.driver_kind,
            "enabled": True,
            **meta.settings,
        }

    # Disable any provider instances not selected for this session
    for inst_id, inst_data in provider_instances.items():
        if inst_id not in selected_instance_ids and isinstance(inst_data, dict):
            inst_data["enabled"] = False

    active_meta = active_driver.get_t3_metadata()
    if active_meta is not None:
        if active_meta.instance_id in provider_instances:
            provider_instances[active_meta.instance_id]["enabled"] = True
        settings["textGenerationModelSelection"] = {
            "instanceId": active_meta.instance_id,
            "model": "default",
        }

    with settings_file.open("w") as f:
        json.dump(settings, f, indent=2)

    return settings_file


def synthesize_t3_policy(
    t3_dir: Path,
    enabled_drivers: list[AgentDriver],
) -> Path:
    """Synthesize enterprise policy.json permitting exactly the workspace's enabled T3 drivers."""
    t3_dir.mkdir(parents=True, exist_ok=True)
    policy_file = t3_dir / "policy.json"

    allowed_drivers: list[str] = []
    for driver in enabled_drivers:
        meta = driver.get_t3_metadata()
        if meta is not None and meta.driver_kind not in allowed_drivers:
            allowed_drivers.append(meta.driver_kind)

    # If no drivers matched, allow at least the default four
    if not allowed_drivers:
        allowed_drivers = ["pi", "opencode", "claudeAgent", "antigravity"]

    policy_data = {
        "schemaVersion": 1,
        "organization": "pa-container",
        "limits": {
            "providers": {
                "allowedDrivers": allowed_drivers,
            }
        },
    }

    with policy_file.open("w") as f:
        json.dump(policy_data, f, indent=2)

    return policy_file
