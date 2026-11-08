from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

if TYPE_CHECKING:
    from pathlib import Path

    from config_types import GatewayConfigItem, ServerConfigItem

sys.dont_write_bytecode = True

from logging_driver import LogCategory, get_category_logger
from registry import (
    LlamaServerModelDef,
    load_gateway_def,
    load_model_def,
    seed_default_models,
)
from yaml_strict import load_yaml_strict

logger = get_category_logger(__name__, LogCategory.AGENT)

"""Model configuration synthesis engine.

Loads models from a lightweight project-level `.pa-container/models.yaml`
allowlist, resolving against global registries `~/.config/pa-container/models/`
and `~/.config/pa-container/gateways/`.
"""


def resolve_models_file(pa_container_dir: Path) -> Path | None:
    """Find the project models configuration file (.pa-container/models.yaml or models.yml)."""
    yaml_candidates = (
        pa_container_dir / "models.yaml",
        pa_container_dir / "models.yml",
    )
    for candidate in yaml_candidates:
        if candidate.is_file():
            return candidate

    return None


def extract_models_from_yaml(
    data: dict[str, Any],
    models_dir: Path | None = None,
    gateways_dir: Path | None = None,
) -> tuple[dict[str, Any], list[ServerConfigItem], set[str], list[GatewayConfigItem], str | None]:
    """Extract server configs, gateways, hostnames, and synthetic providers from models.yaml data.

    Returns:
        (synthetic_models_data, server_configs, llama_hostnames, gateway_configs, default_model)
    """
    server_configs: list[ServerConfigItem] = []
    gateway_configs: list[GatewayConfigItem] = []
    llama_hostnames: set[str] = {"llama"}
    providers: dict[str, dict[str, Any]] = {}

    default_model = data.get("default")
    if default_model is not None:
        default_model = str(default_model).strip() or None

    # Seed default model definition if registry is empty
    seed_default_models(models_dir)

    allow_list = data.get("allow") or []
    for item in allow_list:
        if isinstance(item, str):
            model_id = item.strip()
            provider_name = model_id
            custom_url = None
        elif isinstance(item, dict):
            model_id = str(item.get("id") or item.get("model") or item.get("name") or "").strip()
            provider_name = str(item.get("provider") or item.get("name") or model_id).strip()
            custom_url = item.get("baseUrl") or item.get("base_url")
        else:
            continue

        if not model_id:
            continue

        # 1. Check if model_id is a registered external gateway
        gw_def = load_gateway_def(model_id, registry_dir=gateways_dir)
        if gw_def is not None:
            effective_base_url = custom_url or gw_def.base_url
            gateway_configs.append(
                {
                    "name": provider_name,
                    "gatewayDef": gw_def,
                    "baseUrl": effective_base_url,
                }
            )
            providers[provider_name] = {
                "baseUrl": effective_base_url,
                "api": gw_def.gateway_type,
                "apiKey": f"{provider_name.upper().replace('-', '_')}_API_KEY_PLACEHOLDER",
            }
            if effective_base_url:
                parsed_host = urlparse(effective_base_url).hostname
                if parsed_host and parsed_host not in ("localhost", "127.0.0.1", "::1"):
                    llama_hostnames.add(parsed_host)
            continue

        # 2. Check if model_id is a registered local llama-server model
        m_def = load_model_def(model_id, registry_dir=models_dir)
        if isinstance(m_def, LlamaServerModelDef):
            port = 9999 + len(server_configs)
            effective_base_url = custom_url or f"http://llama:{port}/v1"
            server_configs.append(
                {
                    "name": provider_name,
                    "config": m_def.server_config,
                    "baseUrl": effective_base_url,
                }
            )
            llama_hostnames.add("llama")
            llama_hostnames.add(provider_name)
            if effective_base_url:
                parsed_host = urlparse(effective_base_url).hostname
                if parsed_host and parsed_host not in ("localhost", "127.0.0.1", "::1"):
                    llama_hostnames.add(parsed_host)

            providers[provider_name] = {
                "baseUrl": effective_base_url,
                "api": "openai-completions",
                "apiKey": "not-required",
                "models": [{"id": model_id, "name": model_id}],
            }
            continue

        logger.warning(
            f"Model or gateway '{model_id}' listed in models.yaml allowlist not found "
            f"under registry directories; skipping."
        )

    synthetic_data = {"providers": providers}
    return synthetic_data, server_configs, llama_hostnames, gateway_configs, default_model


def load_project_models(
    pa_container_dir: Path,
    models_dir: Path | None = None,
    gateways_dir: Path | None = None,
) -> tuple[dict[str, Any], list[ServerConfigItem], set[str], list[GatewayConfigItem], str | None, Path]:
    """Load and parse models from `.pa-container/models.yaml`.

    Returns:
        (synthetic_models_data, server_configs, llama_hostnames, gateway_configs, default_model, models_file_path)
    """
    models_path = resolve_models_file(pa_container_dir)
    if models_path is None:
        expected = pa_container_dir / "models.yaml"
        raise FileNotFoundError(f"No models configuration found in {pa_container_dir}. Expected {expected.name}.")

    raw = load_yaml_strict(models_path.read_text())
    data = raw if isinstance(raw, dict) else {}
    synthetic_data, server_configs, llama_hostnames, gateway_configs, default_model = extract_models_from_yaml(
        data, models_dir=models_dir, gateways_dir=gateways_dir
    )
    return synthetic_data, server_configs, llama_hostnames, gateway_configs, default_model, models_path
