from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

"""Shared schema definitions and validation logic for configuration files."""


# ─── Field validation ───────────────────────────────────────────────────────


def _format_type(expected: type | tuple[type, ...]) -> str:
    if isinstance(expected, tuple):
        return " or ".join(_format_type(t) for t in expected)
    return expected.__name__


def _validate_field(value: Any, expected: type | tuple[type, ...], path: str) -> list[str]:
    """Validate a single field's type, returning any error messages."""
    errors: list[str] = []
    if isinstance(value, bool):
        expected_types = expected if isinstance(expected, tuple) else (expected,)
        if bool not in expected_types and (int in expected_types or float in expected_types):
            errors.append(f"  {path}: expected {_format_type(expected)}, got bool (value: {value!r})")
            return errors
    if not isinstance(value, expected):
        errors.append(f"  {path}: expected {_format_type(expected)}, got {type(value).__name__} (value: {value!r})")
    return errors


# ─── Generic recursive schema validator ─────────────────────────────────────


def _validate_schema(data: dict[str, Any], schema: dict[str, Any], path: str = "") -> list[str]:
    """Recursively validate a dictionary structure against a schema specification."""
    errors: list[str] = []
    for key, spec in schema.items():
        current_path = f"{path}.{key}" if path else key

        if key not in data:
            if spec.get("required", True):
                errors.append(f"  {current_path}: required field missing")
            continue

        value = data[key]
        if value is None:
            expected_type = spec["type"]
            allows_none = (
                type(None) in expected_type if isinstance(expected_type, tuple) else expected_type is type(None)
            )
            if not allows_none:
                errors.append(f"  {current_path}: required field missing")
            continue

        errors.extend(_validate_field(value, spec["type"], current_path))
        if not isinstance(value, dict):
            continue

        sub_schema = spec.get("keys", {})
        if sub_schema:
            errors.extend(_validate_schema(value, sub_schema, current_path))

    return errors


# ─── Config.yaml schema ─────────────────────────────────────────────────────
#
# Required top-level keys with their expected types. Sub-keys are validated
# recursively when the parent is present. ``None`` for the type means the value
# can be any YAML type (used for ``egress.allow`` which has a heterogeneous dict).


SCHEMA: dict[str, Any] = {
    "resources": {
        "type": dict,
        "keys": {
            "agent": {
                "type": dict,
                "keys": {
                    "memory": {"type": (str, type(None))},
                    "cpus": {"type": (int, type(None))},
                },
            },
            "proxy": {
                "type": dict,
                "keys": {
                    "memory": {"type": (str, type(None))},
                    "cpus": {"type": (int, type(None))},
                },
            },
        },
    },
    "llama": {
        "type": dict,
        "keys": {
            "startup_timeout": {"type": int},
            "startup_attempts": {"type": int},
        },
    },
    "network": {
        "type": dict,
        "keys": {
            "ipv6": {"type": bool},
            "dns": {"type": str},
        },
    },
    "proxy": {
        "type": dict,
        "keys": {
            "expose_ui": {"type": str},
            "max_view_flows": {"type": (int, type(None))},
            "stream_large_bodies": {"type": (str, int, type(None))},
            "open_browser": {"type": bool},
        },
    },
    "packages": {
        "type": list,
        "required": True,
    },
    "agent": {
        "type": dict,
        "keys": {
            "type": {"type": str, "required": False},
            "command": {"type": (list, str, type(None)), "required": False},
            "options": {"type": dict, "required": False},
            "env": {"type": dict},
            "mounts": {"type": list},
            "capabilities": {"type": list, "required": False},
            "devices": {"type": list, "required": False},
            "read_only_pa_container": {"type": bool},
            "mode": {"type": str, "required": False},
            "ports": {
                "type": dict,
                "required": False,
                "keys": {
                    "expose": {"type": str, "required": False},
                    "publish": {"type": list, "required": False},
                },
            },
        },
    },
    "tmpfs": {
        "type": dict,
        "keys": {
            "paths": {"type": list},
        },
    },
    "volumes": {
        "type": dict,
        "required": False,
        "keys": {
            "paths": {"type": list, "required": False},
        },
    },
    "flow_export": {
        "type": dict,
        "keys": {
            "enabled": {"type": bool},
        },
    },
    "egress": {
        "type": dict,
        "keys": {
            "allow": {"type": dict},
        },
    },
    "security": {
        "type": dict,
        "keys": {
            "read_only_git_hooks": {"type": bool},
            "blocked_mount_paths": {"type": list},
            "blocked_ip_ranges": {"type": list},
            "git_config_allowlist": {"type": list},
        },
    },
    "logging": {
        "type": dict,
        "keys": {
            "log_level": {"type": (str, type(None))},
            "retention": {
                "type": dict,
                "keys": {
                    "max_days": {"type": (int, type(None))},
                    "max_launches": {"type": (int, type(None))},
                },
            },
        },
    },
}


MODELS_YAML_SCHEMA: dict[str, Any] = {
    "default": {"type": (str, type(None)), "required": False},
    "allow": {"type": list, "required": True},
}


GLOBAL_CONFIG_SCHEMA: dict[str, Any] = {
    "schema_version": {"type": str},
    "runtime": {
        "type": dict,
        "keys": {
            "log_level": {"type": str},
            "proxy_upstream_network": {"type": str},
            "open_browser": {"type": bool},
        },
    },
    "llama": {
        "type": dict,
        "keys": {
            "bin": {"type": (str, type(None)), "required": False},
            "build": {
                "type": dict,
                "keys": {
                    "repo": {"type": str},
                    "tag": {"type": str},
                    "backend": {"type": str},
                    "minimal": {"type": bool},
                    "cmake_flags": {"type": list},
                },
            },
        },
    },
    "build": {
        "type": dict,
        "keys": {
            "images": {
                "type": dict,
                "keys": {
                    "agent": {"type": str},
                    "proxy": {"type": str},
                    "base": {"type": str, "required": False},
                    "builder": {"type": str, "required": False},
                },
            },
            "dns": {"type": str},
            "memory_preflight": {"type": bool},
            "fallback_memory_preflight_mib": {"type": int, "required": False},
            "python_optimize": {"type": bool, "required": False},
            "node_source": {"type": str, "required": False},
            "prune_dangling": {"type": bool},
            "purge_build_cache": {"type": bool},
        },
    },
    "logging": {
        "type": dict,
        "keys": {
            "log_level": {"type": str},
            "retention": {
                "type": dict,
                "keys": {
                    "max_days": {"type": (int, type(None))},
                    "max_launches": {"type": (int, type(None))},
                },
            },
        },
    },
}


# ─── Models schema validation ──────────────────────────────────────────────


def _validate_models_yaml(
    data: dict[str, Any],
    gateways_dir: Path | None = None,
) -> list[str]:
    """Validate project-level models.yaml allowlist structure."""
    errors: list[str] = []
    allow = data.get("allow")
    if allow is None:
        errors.append("  allow: required field missing")
        return errors
    if not isinstance(allow, list):
        errors.append(f"  allow: expected list, got {type(allow).__name__}")
        return errors
    if len(allow) == 0:
        errors.append("  allow: list must not be empty")
        return errors

    from registry import load_gateway_def

    seen_agent_native_providers: set[str] = set()

    for i, item in enumerate(allow):
        gw_def = None
        model_id = ""
        if isinstance(item, str):
            model_id = item.strip()
            if not model_id:
                errors.append(f"  allow[{i}]: item must not be empty string")
                continue
            gw_def = load_gateway_def(model_id, registry_dir=gateways_dir)
            if gw_def is not None and gw_def.auth is not None:
                if gw_def.auth.type == "api-key":
                    errors.append(
                        f"  allow[{i}]: gateway '{model_id}' requires authentication. "
                        "It must be configured as a mapping with non-empty 'containerEnvVar', "
                        "'keyringService', and 'keyringAccount'."
                    )
                elif gw_def.auth.type == "openid":
                    errors.append(
                        f"  allow[{i}]: gateway '{model_id}' requires authentication. "
                        "It must be configured as a mapping with non-empty 'containerEnvVar'."
                    )
        elif isinstance(item, dict):
            m_id = item.get("id")
            if not m_id or not isinstance(m_id, str):
                errors.append(f"  allow[{i}]: expected non-empty 'id' string")
                continue
            model_id = m_id.strip()
            gw_def = load_gateway_def(model_id, registry_dir=gateways_dir)
            if gw_def is not None and gw_def.auth is not None:
                if gw_def.auth.type == "api-key":
                    for req_field in ("containerEnvVar", "keyringService", "keyringAccount"):
                        val = item.get(req_field)
                        if not val or not isinstance(val, str) or not val.strip():
                            errors.append(
                                f"  allow[{i}]: gateway '{model_id}' requires '{req_field}' to be a non-empty string"
                            )
                elif gw_def.auth.type == "openid":
                    val = item.get("containerEnvVar")
                    if not val or not isinstance(val, str) or not val.strip():
                        errors.append(
                            f"  allow[{i}]: gateway '{model_id}' requires 'containerEnvVar' to be a non-empty string"
                        )
        else:
            errors.append(f"  allow[{i}]: expected string or dict, got {type(item).__name__}")
            continue

        if gw_def is not None and gw_def.auth is not None and gw_def.auth.type == "agent-native":
            provider = gw_def.gateway_type or gw_def.id
            if provider in seen_agent_native_providers:
                errors.append(
                    f"  allow[{i}]: gateway '{model_id}' with auth.type 'agent-native' can only be instantiated once per provider ('{provider}')"
                )
            seen_agent_native_providers.add(provider)

    return errors


def validate_model_def_data(data: dict[str, Any], model_id: str = "") -> list[str]:
    """Validate local model definition dictionary (~/.config/pa-container/models/<id>.yaml)."""
    errors: list[str] = []
    hf_models = data.get("hfModels")
    if hf_models is None:
        errors.append(f"model definition '{model_id}': hfModels must not be null")
    elif not isinstance(hf_models, dict):
        errors.append(f"model definition '{model_id}': hfModels expected dict, got {type(hf_models).__name__}")
    elif len(hf_models) == 0:
        errors.append(f"model definition '{model_id}': hfModels must not be empty")
    else:
        if "main" not in hf_models:
            errors.append(f"model definition '{model_id}': hfModels.main is required")
        required_fields = ("fileFlag", "repo", "file")
        for m_name, m_cfg in hf_models.items():
            if not isinstance(m_cfg, dict):
                errors.append(f"model definition '{model_id}': hfModels.{m_name} expected dict")
                continue
            for f in required_fields:
                val = m_cfg.get(f)
                if val is None or not isinstance(val, str) or not val.strip():
                    errors.append(f"model definition '{model_id}': hfModels.{m_name}.{f} must be a non-empty string")

    flags = data.get("flags")
    if flags is not None:
        if not isinstance(flags, list):
            errors.append(f"model definition '{model_id}': flags expected list")
        else:
            for i, item in enumerate(flags):
                if not isinstance(item, (str, int, float)):
                    errors.append(
                        f"model definition '{model_id}': flags[{i}] expected str/int/float, got {type(item).__name__}"
                    )

    return errors


def _validate_agents(data: dict[str, Any]) -> list[str]:
    """Validate that legacy 'agents' section is rejected."""
    errors: list[str] = []
    if "agents" in data:
        errors.append(
            "  agents: 'agents' section is obsolete in schema 3.0.0. "
            "Specify agent packages directly in 'packages:' (e.g. packages: [pi])."
        )
    return errors
