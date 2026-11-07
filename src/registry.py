from __future__ import annotations

import sys

sys.dont_write_bytecode = True

"""Global model and gateway registry loader.

- Gateways: ~/.config/pa-container/gateways/<gateway_id>.yaml (provider-level external gateways)
- Models:   ~/.config/pa-container/models/<model_id>.yaml     (model-level local llama-server definitions)
"""

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from config import (
    GLOBAL_CHAT_TEMPLATES_DIR,
    GLOBAL_GATEWAYS_REGISTRY_DIR,
    GLOBAL_MODELS_REGISTRY_DIR,
    REPO_ROOT,
)
from logging_driver import LogCategory, get_category_logger
from models import ServerConfig

logger = get_category_logger(__name__, LogCategory.MODEL)


# ─── Data Structures ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class GatewayAuth:
    """Authentication configuration for a model gateway."""

    type: str = "openid"
    discovery_url: str | None = None
    authorization_url: str | None = None
    token_url: str | None = None
    client_id: str | None = None
    scopes: list[str] = field(default_factory=list)
    token_cache: Path | None = None
    env_var: str | None = None
    keyring_service: str | None = None
    keyring_account: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GatewayAuth:
        token_cache_val = data.get("tokenCache")
        token_cache_path = Path(token_cache_val).expanduser() if token_cache_val else None
        return cls(
            type=data.get("type", "openid"),
            discovery_url=data.get("discoveryUrl"),
            authorization_url=data.get("authorizationUrl"),
            token_url=data.get("tokenUrl"),
            client_id=data.get("clientId"),
            scopes=data.get("scopes", []),
            token_cache=token_cache_path,
            env_var=data.get("envVar"),
            keyring_service=data.get("keyringService"),
            keyring_account=data.get("keyringAccount"),
        )


@dataclass(frozen=True)
class GatewayDef:
    """Definition for an external model gateway (e.g. Opper, Nitor Gateway)."""

    id: str
    base_url: str
    gateway_type: str = "openai-compat"
    description: str = ""
    auth: GatewayAuth | None = None

    @classmethod
    def from_dict(cls, gateway_id: str, data: dict[str, Any]) -> GatewayDef:
        auth_data = data.get("auth")
        auth = GatewayAuth.from_dict(auth_data) if auth_data else None
        return cls(
            id=data.get("id", gateway_id),
            base_url=data.get("baseUrl", ""),
            gateway_type=data.get("type", "openai-compat"),
            description=data.get("description", ""),
            auth=auth,
        )


@dataclass(frozen=True)
class LlamaServerModelDef:
    """Model definition managed locally via a host llama-server process."""

    id: str
    server_config: ServerConfig
    description: str = ""

    @classmethod
    def from_dict(cls, model_id: str, data: dict[str, Any]) -> LlamaServerModelDef:
        server_config = ServerConfig.from_dict(
            {
                "hfModels": data.get("hfModels", {}),
                "flags": data.get("flags", []),
            }
        )
        return cls(
            id=data.get("id", model_id),
            server_config=server_config,
            description=data.get("description", ""),
        )


# ─── Bundled Seed Template Directories ───────────────────────────────────────

BUNDLED_MODELS_DIR: Path = REPO_ROOT / "coding-agent" / "default" / "global" / "models"
BUNDLED_CHAT_TEMPLATES_DIR: Path = REPO_ROOT / "coding-agent" / "default" / "global" / "chat-templates"


# ─── Registry Loader Functions ───────────────────────────────────────────────


def get_models_dir(override_dir: Path | None = None) -> Path:
    """Return the active global models registry directory."""
    return override_dir if override_dir is not None else GLOBAL_MODELS_REGISTRY_DIR


def get_gateways_dir(override_dir: Path | None = None) -> Path:
    """Return the active global gateways registry directory."""
    return override_dir if override_dir is not None else GLOBAL_GATEWAYS_REGISTRY_DIR


def get_chat_templates_dir(override_dir: Path | None = None) -> Path:
    """Return the active global chat templates directory."""
    return override_dir if override_dir is not None else GLOBAL_CHAT_TEMPLATES_DIR


def seed_default_chat_templates(templates_dir: Path | None = None) -> list[str]:
    """Seed bundled chat templates if missing in the destination chat templates directory."""
    target_dir = get_chat_templates_dir(templates_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    seeded: list[str] = []

    bundled_dir = BUNDLED_CHAT_TEMPLATES_DIR
    if bundled_dir.is_dir():
        for item in sorted(bundled_dir.iterdir()):
            if item.is_dir():
                target_sub = target_dir / item.name
                jinja_src = item / "chat_template.jinja"
                jinja_dst = target_sub / "chat_template.jinja"
                if not jinja_dst.exists() and jinja_src.is_file():
                    target_sub.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(jinja_src, jinja_dst)
                    seeded.append(str(jinja_dst.relative_to(target_dir)))
                    logger.info(f"Seeded default chat template: {jinja_dst}")

    return seeded


def seed_default_models(registry_dir: Path | None = None) -> list[str]:
    """Seed default model definitions if the models registry directory is empty or missing."""
    target_dir = get_models_dir(registry_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    templates_dir = target_dir.parent / "chat-templates" if registry_dir is not None else None
    seed_default_chat_templates(templates_dir)

    seeded: list[str] = []
    existing = list(target_dir.glob("*.yaml"))
    if not existing:
        bundled_dir = BUNDLED_MODELS_DIR
        if bundled_dir.is_dir():
            for model_file in sorted(bundled_dir.glob("*.yaml")):
                dst = target_dir / model_file.name
                shutil.copy2(model_file, dst)
                seeded.append(dst.name)
                logger.info(f"Seeded default model definition: {dst}")

    return seeded


def _find_definition_file(name: str, target_dir: Path) -> tuple[Path, dict[str, Any]] | None:
    if not target_dir.exists():
        return None

    candidate = target_dir / f"{name}.yaml"
    if candidate.is_file():
        try:
            from yaml_strict import load_yaml_file

            data = load_yaml_file(candidate)
        except Exception as e:
            logger.error(f"Failed to parse registry definition {candidate}: {e}")
            return None

        if not isinstance(data, dict):
            logger.error(f"Registry definition {candidate} must be a dictionary.")
            return None

        return candidate, data

    return None


def load_gateway_def(gateway_id: str, registry_dir: Path | None = None) -> GatewayDef | None:
    """Load an external gateway definition by ID from ~/.config/pa-container/gateways/."""
    target_dir = get_gateways_dir(registry_dir)
    found = _find_definition_file(gateway_id, target_dir)
    if not found:
        return None
    _, data = found
    return GatewayDef.from_dict(gateway_id, data)


def load_model_def(model_id: str, registry_dir: Path | None = None) -> LlamaServerModelDef | None:
    """Load a local llama-server model definition by ID from ~/.config/pa-container/models/."""
    target_dir = get_models_dir(registry_dir)
    found = _find_definition_file(model_id, target_dir)
    if not found:
        return None
    _, data = found

    from schema_common import validate_model_def_data

    def_errors = validate_model_def_data(data, model_id=model_id)
    if def_errors:
        for err in def_errors:
            logger.error(f"Model definition error in {model_id}.yaml: {err}")
        return None

    return LlamaServerModelDef.from_dict(model_id, data)


def list_gateway_defs(registry_dir: Path | None = None) -> list[GatewayDef]:
    """List all valid gateway definitions found in the gateways registry directory."""
    target_dir = get_gateways_dir(registry_dir)
    if not target_dir.exists():
        return []

    defs: list[GatewayDef] = []
    for path in sorted(target_dir.iterdir()):
        if path.suffix == ".yaml" and path.is_file():
            gw_def = load_gateway_def(path.stem, target_dir)
            if gw_def:
                defs.append(gw_def)
    return defs


def list_model_defs(registry_dir: Path | None = None) -> list[LlamaServerModelDef]:
    """List all valid model definitions found in the models registry directory."""
    target_dir = get_models_dir(registry_dir)
    if not target_dir.exists():
        return []

    defs: list[LlamaServerModelDef] = []
    for path in sorted(target_dir.iterdir()):
        if path.suffix == ".yaml" and path.is_file():
            m_def = load_model_def(path.stem, target_dir)
            if m_def:
                defs.append(m_def)
    return defs
