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
    "tools": {
        "type": dict,
        "required": False,
        "keys": {
            "include": {"type": list, "required": False},
        },
    },
    "agents": {
        "type": dict,
        "keys": {
            "enabled": {"type": list},
            "default": {"type": str},
        },
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
    "nested_containers": {
        "type": dict,
        "keys": {
            "enabled": {"type": bool},
            "storage": {"type": str},
            "security": {"type": str},
            "ports": {
                "type": dict,
                "keys": {
                    "expose": {"type": str},
                    "publish": {"type": list},
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
    "git": {
        "type": dict,
        "keys": {
            "safe_directory": {"type": bool},
            "rewrite_ssh_to_https": {"type": bool},
        },
    },
    "source_control": {
        "type": dict,
        "required": False,
        "keys": {
            "enabled": {"type": bool, "required": False},
            "auto_detect_host_cli": {"type": bool, "required": False},
            "setup_git_credentials": {"type": bool, "required": False},
            "providers": {"type": dict, "required": False},
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
    "desktop": {
        "type": dict,
        "keys": {
            "enabled": {"type": bool},
            "resolution": {"type": str},
            "compositor": {"type": str},
            "open_browser": {"type": bool},
            "vnc": {
                "type": dict,
                "keys": {
                    "enabled": {"type": bool},
                    "port": {"type": (int, str)},
                    "expose": {"type": str},
                },
            },
            "novnc": {
                "type": dict,
                "keys": {
                    "enabled": {"type": bool},
                    "port": {"type": (int, str)},
                    "expose": {"type": str},
                },
            },
            "gpu": {
                "type": dict,
                "keys": {
                    "enabled": {"type": (bool, str)},
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
            "bridge_interface": {"type": (str, type(None)), "required": False},
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
                    "builder": {"type": str},
                },
            },
            "dns": {"type": str},
            "python_optimize": {"type": bool},
            "memory_preflight": {"type": bool},
            "node_source": {"type": str},
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
    "desktop": {
        "type": dict,
        "required": False,
        "keys": {
            "open_browser": {"type": bool, "required": False},
        },
    },
}


# ─── Models schema validation ──────────────────────────────────────────────


def _validate_models_yaml(
    data: dict[str, Any],
    models_dir: Path | None = None,
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

    for i, item in enumerate(allow):
        if isinstance(item, str):
            if not item.strip():
                errors.append(f"  allow[{i}]: item must not be empty string")
        elif isinstance(item, dict):
            m_id = item.get("id")
            if not m_id or not isinstance(m_id, str):
                errors.append(f"  allow[{i}]: expected non-empty 'id' string")
        else:
            errors.append(f"  allow[{i}]: expected string or dict, got {type(item).__name__}")

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
    """Validate agents section: must have at least one enabled agent from AVAILABLE_AGENTS."""
    errors: list[str] = []
    agents_sec = data.get("agents")
    if agents_sec is None:
        return errors
    if not isinstance(agents_sec, dict):
        return errors

    enabled = agents_sec.get("enabled")
    if enabled is None:
        return errors
    if not isinstance(enabled, list):
        return errors

    from agents import AVAILABLE_AGENTS

    if len(enabled) == 0:
        errors.append("  agents.enabled: configuration must have at least one agent enabled")
        return errors

    valid_enabled = []
    for item in enabled:
        if not isinstance(item, str):
            errors.append(f"  agents.enabled: expected string agent name, got {type(item).__name__} (value: {item!r})")
        elif item.lower() not in AVAILABLE_AGENTS:
            errors.append(
                f"  agents.enabled: unknown agent '{item}'. Available agents: {', '.join(sorted(AVAILABLE_AGENTS))}"
            )
        else:
            valid_enabled.append(item.lower())

    default = agents_sec.get("default")
    if default is not None:
        if not isinstance(default, str):
            errors.append(f"  agents.default: expected string agent name, got {type(default).__name__}")
        elif default.lower() not in AVAILABLE_AGENTS:
            errors.append(
                f"  agents.default: unknown agent '{default}'. Available agents: {', '.join(sorted(AVAILABLE_AGENTS))}"
            )
        elif default.lower() not in valid_enabled:
            errors.append(f"  agents.default: agent '{default}' is set as default but is not enabled in agents.enabled")

    return errors
