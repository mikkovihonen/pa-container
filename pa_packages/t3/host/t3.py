from __future__ import annotations

import contextlib
import hashlib
import json
import sys
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

    from pa_packages.agents.host.base import AgentDriver

sys.dont_write_bytecode = True

"""T3 Code configuration and policy synthesis for coding agents."""


def sync_antigravity_token(t3_dir: Path, project_dir: Path | None) -> None:
    """Sync Antigravity CLI OAuth token to T3 ACP credentials and cache without host extraction.

    Credential extraction from the ACP runtime archive occurs exclusively inside
    the container session via t3-sync-antigravity.py. On the host, this only
    updates existing tokens or seeds the initial provider status cache.
    """
    if not project_dir:
        return
    token_file = project_dir / ".pa-container" / "agents" / "antigravity" / "cli" / "antigravity-oauth-token"
    if not token_file.is_file():
        return
    with contextlib.suppress(Exception):
        data = json.loads(token_file.read_text())
        refresh_token = data.get("token", {}).get("refresh_token")
        if not refresh_token:
            return
        key = hashlib.sha256(b"antigravity").hexdigest()
        acp_dir = t3_dir / "userdata" / "providers" / "antigravity" / key / "antigravity-acp"
        acp_token_file = acp_dir / "acp_token.json"

        # If acp_token.json was already generated inside container, update refresh_token
        # without extracting or touching any binaries on the host.
        if acp_token_file.is_file():
            with contextlib.suppress(Exception):
                token_data = json.loads(acp_token_file.read_text())
                if token_data.get("client_id") and token_data.get("client_secret"):
                    token_data["refresh_token"] = refresh_token
                    acp_token_file.write_text(json.dumps(token_data, indent=2))
                    with contextlib.suppress(OSError):
                        acp_token_file.chmod(0o600)

        cache_dir = t3_dir / "caches"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / "antigravity.json"
        cache_data = {}
        if cache_file.is_file():
            with contextlib.suppress(Exception):
                cache_data = json.loads(cache_file.read_text())
        now_iso = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        cache_data.pop("message", None)
        cache_data.pop("unavailableReason", None)
        cache_data.update(
            {
                "displayName": "Antigravity",
                "showInteractionModeToggle": False,
                "supportedRuntimeModes": ["approval-required", "auto-accept-edits", "full-access"],
                "enabled": True,
                "installed": True,
                "version": cache_data.get("version") or "1.4.5",
                "status": "ready",
                "auth": {
                    "status": "authenticated",
                    "type": "oauth-personal",
                    "label": "Google account",
                },
                "setup": {"canAuthenticate": True, "canInstall": True},
                "checkedAt": cache_data.get("checkedAt") or now_iso,
                "slashCommands": cache_data.get("slashCommands") or [],
                "skills": cache_data.get("skills") or [],
                "instanceId": "antigravity",
                "driver": "antigravity",
                "continuation": {"groupKey": "antigravity:instance:antigravity"},
                "supportsConversationRollback": False,
                "supportsTextGeneration": True,
            }
        )
        if not cache_data.get("models"):
            cache_data["models"] = [
                {
                    "slug": "gemini-3.8-flash",
                    "name": "Gemini 3.8 Flash",
                    "isCustom": False,
                    "capabilities": {
                        "optionDescriptors": [
                            {
                                "id": "thinking_level",
                                "label": "Thinking Level",
                                "type": "select",
                                "options": [
                                    {"id": "low", "label": "Low"},
                                    {"id": "medium", "label": "Medium"},
                                    {"id": "high", "label": "High", "isDefault": True},
                                ],
                            }
                        ]
                    },
                    "isDefault": True,
                }
            ]
        else:
            for m in cache_data["models"]:
                if isinstance(m, dict) and "isCustom" not in m:
                    m["isCustom"] = False
        cache_file.write_text(json.dumps(cache_data, indent=2))


def synthesize_t3_settings(
    t3_dir: Path,
    active_driver: AgentDriver,
    enabled_drivers: list[AgentDriver],
    project_dir: Path | None = None,
) -> Path:
    """Synthesize or update T3 Code userdata settings.json for active and enabled agents."""
    sync_antigravity_token(t3_dir, project_dir)
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
        meta = driver.get_orchestrator_metadata("t3")
        if meta is None:
            continue
        selected_instance_ids.add(meta.instance_id)
        existing = provider_instances.get(meta.instance_id, {})
        if not isinstance(existing, dict):
            existing = {}
        existing_config = existing.get("config", {})
        if not isinstance(existing_config, dict):
            existing_config = {}
        merged_config = {**existing_config, **meta.settings}
        provider_instances[meta.instance_id] = {
            **existing,
            "driver": meta.provider_kind,
            "enabled": True,
            "config": merged_config,
            **meta.settings,
        }

    # Disable any provider instances not selected for this session
    for inst_id, inst_data in provider_instances.items():
        if inst_id not in selected_instance_ids and isinstance(inst_data, dict):
            inst_data["enabled"] = False

    active_meta = active_driver.get_orchestrator_metadata("t3")
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
        meta = driver.get_orchestrator_metadata("t3")
        if meta is not None and meta.provider_kind not in allowed_drivers:
            allowed_drivers.append(meta.provider_kind)

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
