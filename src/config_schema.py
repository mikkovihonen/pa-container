import sys
from pathlib import Path
from typing import Any

import yaml

from schema_common import (
    GLOBAL_CONFIG_SCHEMA,
    MODELS_YAML_SCHEMA,
    SCHEMA,
    _validate_agents,
    _validate_models_yaml,
    _validate_schema,
)
from version import get_git_tag_version
from yaml_strict import DuplicateKeyError, check_duplicate_keys, load_yaml_strict

sys.dont_write_bytecode = True

"""Configuration schema validation for `config.yaml` and `models.yaml`."""


# ─── Version from git tags ──────────────────────────────────────────────────


def get_app_version(repo_root: Path | None = None) -> str | None:
    """Retrieve the current pa-container version from git tags on the repository."""
    r_root = repo_root if repo_root is not None else Path(__file__).resolve().parent.parent
    return get_git_tag_version(r_root)


#: Marker text in the stale-version error.
SCHEMA_VERSION_MISMATCH = "schema_version mismatch"


# ─── Validation ─────────────────────────────────────────────────────────────
# All helpers are imported from ``schema_common.py``.
from packages import discover_packages


def _validate_packages(data: dict[str, Any]) -> list[str]:
    """Validate packages list against discovered Agent Capability Packages and ensure at least one agent package."""
    errors: list[str] = []
    packages_list = data.get("packages")
    if packages_list is None:
        errors.append("  packages: required field missing")
        return errors
    if not isinstance(packages_list, list):
        errors.append(f"  packages: expected list, got {type(packages_list).__name__} (value: {packages_list!r})")
        return errors

    manifests = discover_packages()
    available_packages = set(manifests.keys())
    agent_packages_count = 0
    for item in packages_list:
        if not isinstance(item, str):
            errors.append(f"  packages: expected string package name, got {type(item).__name__} (value: {item!r})")
        elif item not in available_packages:
            errors.append(
                f"  packages: unknown package '{item}'. Available packages: {', '.join(sorted(available_packages))}"
            )
        else:
            if manifests[item].category == "agents":
                agent_packages_count += 1

    if agent_packages_count == 0:
        errors.append(
            "  packages: configuration must include at least one agent package (category: 'agents'), "
            "e.g. 'pi', 'opencode', 'antigravity', 'claude-code'"
        )
    return errors


def _validate_package_configs(data: dict[str, Any]) -> list[str]:
    """Validate package-specific root configuration sections contributed by ACPs."""
    errors: list[str] = []
    manifests = discover_packages()
    from packages.discovery import get_package_dir
    from packages.loader import load_acp_plugin

    packages_list = data.get("packages") or []
    active_pkg_names = {p for p in packages_list if isinstance(p, str)}

    for manifest in manifests.values():
        config_key = manifest.extension.config_key
        if not config_key or config_key not in data:
            continue

        section = data[config_key]
        if not isinstance(section, dict):
            errors.append(f"  {config_key}: expected dict, got {type(section).__name__}")
            continue

        is_enabled = bool(section.get("enabled", False))
        if is_enabled and manifest.name not in active_pkg_names:
            errors.append(
                f"  {config_key}: section is enabled ('enabled: true'), but package '{manifest.name}' "
                f"is missing from 'packages:'. Add '{manifest.name}' to 'packages:' in .pa-container/config.yaml."
            )

        pkg_dir = get_package_dir(manifest.name)
        try:
            plugin = load_acp_plugin(manifest, pkg_dir)
            if plugin is not None:
                schema_contrib = plugin.contribute_config_schema()
                if isinstance(schema_contrib, dict):
                    sub_keys = schema_contrib.get("keys", {})
                    if sub_keys:
                        sub_errors = _validate_schema(section, sub_keys, config_key)
                        errors.extend(sub_errors)
        except Exception as e:
            errors.append(f"  {config_key}: error validating package configuration: {e}")

    return errors


def validate_config(config_path: Path) -> tuple[bool, list[str], str | None]:
    """Validate `config.yaml` structure, required fields, and schema version against git release tag.

    Returns:
        tuple of (is_valid, error_list, schema_version_string).
    """
    errors: list[str] = []

    if not config_path.exists():
        errors.append(f"Config file not found: {config_path}")
        return False, errors, None

    try:
        raw_data = load_yaml_strict(config_path.read_text())
        if not isinstance(raw_data, dict):
            errors.append("Config file must be a YAML mapping")
            return False, errors, None
        data = raw_data
    except DuplicateKeyError as e:
        # Called out separately from other syntax errors because it is the one
        # YAML mistake that otherwise parses clean and loses a setting silently.
        errors.append(f"Config file has a duplicate key: {e}")
        errors.append("  Remove the repeated key — YAML keeps only the last occurrence.")
        return False, errors, None
    except yaml.YAMLError as e:
        errors.append(f"Config file is not valid YAML: {e}")
        return False, errors, None

    # Extract schema_version
    schema_version = data.get("schema_version")
    if schema_version is None:
        errors.append("  schema_version: required field missing")
        return False, errors, None

    schema_version_str = str(schema_version)

    # Check schema_version matches app version
    app_version = get_app_version()
    if app_version is not None and schema_version_str != app_version:
        errors.append(
            f"  {SCHEMA_VERSION_MISMATCH}: config has '{schema_version_str}', "
            f"but pa-container version is '{app_version}' (from git tag). "
            f"Delete .pa-container and re-run to re-seed, or update schema_version in config.yaml."
        )

    # Validate schema
    schema_errors = _validate_schema(data, SCHEMA)
    if schema_errors:
        errors.extend(schema_errors)

    # Validate packages
    package_errors = _validate_packages(data)
    if package_errors:
        errors.extend(package_errors)

    # Validate agents
    agent_errors = _validate_agents(data)
    if agent_errors:
        errors.extend(agent_errors)

    # Validate package configurations
    package_config_errors = _validate_package_configs(data)
    if package_config_errors:
        errors.extend(package_config_errors)

    is_valid = len(errors) == 0
    return is_valid, errors, schema_version_str


def validate_global_config(
    config_path: Path,
    repo_root: Path | None = None,
    expected_version: str | None = None,
) -> tuple[bool, list[str], str | None]:
    """Validate global ~/.config/pa-container/config.yaml structure, required fields, and schema version.

    Returns:
        tuple of (is_valid, error_list, schema_version_string).
    """
    errors: list[str] = []

    if not config_path.exists():
        errors.append(f"Global config file not found: {config_path}")
        return False, errors, None

    try:
        raw_data = load_yaml_strict(config_path.read_text())
        if not isinstance(raw_data, dict):
            errors.append("Global config file must be a YAML mapping")
            return False, errors, None
        data = raw_data
    except DuplicateKeyError as e:
        errors.append(f"Global config file has a duplicate key: {e}")
        errors.append("  Remove the repeated key — YAML keeps only the last occurrence.")
        return False, errors, None
    except yaml.YAMLError as e:
        errors.append(f"Global config file is not valid YAML: {e}")
        errors.append("  Remove the repeated key — YAML keeps only the last occurrence.") if False else None
        return False, errors, None

    schema_version = data.get("schema_version")
    if schema_version is None:
        errors.append("  schema_version: required field missing")
        return False, errors, None

    schema_version_str = str(schema_version)

    app_version = expected_version or get_app_version(repo_root=repo_root)
    if app_version is not None and schema_version_str != app_version:
        errors.append(
            f"  {SCHEMA_VERSION_MISMATCH}: global config has '{schema_version_str}', "
            f"but pa-container version is '{app_version}' (from git tag). "
            f"Delete ~/.config/pa-container/config.yaml and re-run to re-seed, or update schema_version."
        )

    schema_errors = _validate_schema(data, GLOBAL_CONFIG_SCHEMA)
    if schema_errors:
        errors.extend(schema_errors)

    is_valid = len(errors) == 0
    return is_valid, errors, schema_version_str


#: Per-project YAML files checked for duplicate keys at launch. ``config.yaml``
#: is validated in full by ``validate_config``; the other two are consumed by
#: the proxy addons inside the proxy container, where a dropped key is invisible
#: from the host — an allowlist rule silently discarded is a security-relevant
#: failure, so the check happens here rather than after the proxy is up.
PROJECT_YAML_FILES = ("config.yaml", "allowlist.yaml", "token_replacer.yaml")


def validate_project_yaml(config_dir: Path) -> list[str]:
    """Scan all project YAML files (`config.yaml`, `allowlist.yaml`, `token_replacer.yaml`, `models.yaml`) for duplicate mapping keys."""
    errors: list[str] = []
    for name in PROJECT_YAML_FILES:
        errors.extend(check_duplicate_keys(config_dir / name))
    if (config_dir / "models.yaml").exists():
        errors.extend(check_duplicate_keys(config_dir / "models.yaml"))
    elif (config_dir / "models.yml").exists():
        errors.extend(check_duplicate_keys(config_dir / "models.yml"))
    return errors


# ─── Models validation ────────────────────────────────────────────────────────


def validate_models(
    models_path: Path,
    gateways_dir: Path | None = None,
    models_dir: Path | None = None,
) -> tuple[bool, list[str]]:
    """Validate `.pa-container/models.yaml` structure."""
    errors: list[str] = []

    if not models_path.exists():
        errors.append(f"Models file not found: {models_path}")
        return False, errors

    if models_path.suffix.lower() != ".yaml":
        errors.append(f"Models file must be a YAML file (.yaml), got: {models_path.name}")
        return False, errors

    try:
        dup_errors = check_duplicate_keys(models_path)
        if dup_errors:
            errors.extend(dup_errors)
            return False, errors
        data = load_yaml_strict(models_path.read_text())
    except Exception as e:
        errors.append(f"Models file is not valid YAML: {e}")
        return False, errors

    if not isinstance(data, dict):
        errors.append("Models file must be a YAML mapping")
        return False, errors

    schema_errors = _validate_schema(data, MODELS_YAML_SCHEMA)
    if schema_errors:
        errors.extend(schema_errors)
        return False, errors

    yaml_errors = _validate_models_yaml(data, gateways_dir=gateways_dir)
    if yaml_errors:
        errors.extend(yaml_errors)

    is_valid = len(errors) == 0
    return is_valid, errors
