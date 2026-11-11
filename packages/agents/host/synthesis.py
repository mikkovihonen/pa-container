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
    seed_default_gateways,
    seed_default_models,
)
from yaml_strict import load_yaml_strict

logger = get_category_logger(__name__, LogCategory.AGENT)

"""Model configuration synthesis engine.

Loads models from a lightweight project-level `.pa-container/models.yaml`
allowlist, resolving against global registries `~/.config/pa-container/models/`
and `~/.config/pa-container/gateways/`.
"""


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

    # Seed default model and gateway definitions if registries are empty
    seed_default_models(models_dir)
    seed_default_gateways(gateways_dir)

    allow_list = data.get("allow") or []
    seen_agent_native_providers: set[str] = set()
    for item in allow_list:
        if isinstance(item, str):
            model_id = item.strip()
            provider_name = model_id
            custom_url = None
        elif isinstance(item, dict):
            raw_id = item.get("id")
            if not raw_id or not isinstance(raw_id, str):
                raise ValueError(f"Invalid models.yaml entry {item!r}: 'id' must be a non-empty string")
            model_id = raw_id.strip()
            provider_name = str(item.get("provider") or model_id).strip()
            custom_url = item.get("baseUrl")
        else:
            continue

        if not model_id:
            continue

        # 1. Check if model_id is a registered external gateway
        gw_def = load_gateway_def(model_id, registry_dir=gateways_dir)
        if gw_def is not None:
            if gw_def.auth is not None and gw_def.auth.type in ("api-key", "openid"):
                if not isinstance(item, dict):
                    raise ValueError(
                        f"Gateway '{model_id}' requires authentication. It must be declared as a mapping in models.yaml."
                    )
                if gw_def.auth.type == "api-key":
                    for req_field in ("containerEnvVar", "keyringService", "keyringAccount"):
                        val = item.get(req_field)
                        if not val or not isinstance(val, str) or not val.strip():
                            raise ValueError(
                                f"Gateway '{model_id}' requires '{req_field}' to be a non-empty string in models.yaml"
                            )
                elif gw_def.auth.type == "openid":
                    val = item.get("containerEnvVar")
                    if not val or not isinstance(val, str) or not val.strip():
                        raise ValueError(
                            f"Gateway '{model_id}' requires 'containerEnvVar' to be a non-empty string in models.yaml"
                        )
            elif gw_def.auth is not None and gw_def.auth.type == "agent-native":
                provider = gw_def.gateway_type or gw_def.id
                if provider in seen_agent_native_providers:
                    raise ValueError(
                        f"Gateway '{model_id}' with auth.type 'agent-native' can only be instantiated once per provider ('{provider}')"
                    )
                seen_agent_native_providers.add(provider)

            effective_base_url = custom_url or gw_def.base_url
            gw_item: GatewayConfigItem = {
                "name": provider_name,
                "gatewayDef": gw_def,
                "baseUrl": effective_base_url,
            }
            if isinstance(item, dict):
                if item.get("containerEnvVar"):
                    gw_item["containerEnvVar"] = str(item["containerEnvVar"]).strip()
                if item.get("keyringService"):
                    gw_item["keyringService"] = str(item["keyringService"]).strip()
                if item.get("keyringAccount"):
                    gw_item["keyringAccount"] = str(item["keyringAccount"]).strip()

            gateway_configs.append(gw_item)
            providers[provider_name] = {
                "baseUrl": effective_base_url,
                "api": gw_def.gateway_type,
                "apiKey": f"{provider_name.upper().replace('-', '_')}_API_KEY_PLACEHOLDER",
            }
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

        raise ValueError(
            f"Model or gateway '{model_id}' listed in models.yaml allowlist not found under registry directories."
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
    models_path = pa_container_dir / "models.yaml"
    if not models_path.is_file():
        raise FileNotFoundError(f"No models configuration found in {pa_container_dir}. Expected models.yaml.")

    raw = load_yaml_strict(models_path.read_text())
    data = raw if isinstance(raw, dict) else {}
    synthetic_data, server_configs, llama_hostnames, gateway_configs, default_model = extract_models_from_yaml(
        data, models_dir=models_dir, gateways_dir=gateways_dir
    )
    return synthetic_data, server_configs, llama_hostnames, gateway_configs, default_model, models_path
