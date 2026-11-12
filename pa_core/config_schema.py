import contextlib
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


def _validate_canonical_component(
    comp_type: str,
    name: str,
    val: Any,
    manifest_secrets: list[Any],
    path_prefix: str,
    allow_features: bool = False,
) -> list[str]:
    """Reusable validation for any canonical component (package or feature)."""
    errors: list[str] = []
    spec_name = "Canonical Package Specification" if comp_type == "package" else "Canonical Feature Specification"
    if not isinstance(val, dict):
        expected_keys = "'features', 'config', and 'secrets'" if allow_features else "'config' and 'secrets'"
        errors.append(
            f"  {path_prefix}: {spec_name} required. Expected mapping containing {expected_keys}, "
            f"got {type(val).__name__}. Shorthand syntax is not supported."
        )
        return errors

    allowed_keys = {"features", "config", "secrets"} if allow_features else {"config", "secrets"}
    unrecognized_keys = set(val.keys()) - allowed_keys
    if unrecognized_keys:
        msg_keys = (
            "Configuration must be under 'config:', features under 'features:', and secrets under 'secrets:'."
            if allow_features
            else "Configuration must be under 'config:' and secrets under 'secrets:'."
        )
        errors.append(f"  {path_prefix}: unrecognized key(s) {sorted(unrecognized_keys)}. {msg_keys}")

    # 1. Validate config
    if "config" not in val:
        errors.append(f"  {path_prefix}: missing required key 'config' (use 'config: {{}}' if default)")
    elif not isinstance(val["config"], dict):
        errors.append(f"  {path_prefix}.config: expected mapping, got {type(val['config']).__name__}")

    # 2. Validate secrets
    mapped_secret_names: set[str] = set()
    if "secrets" not in val:
        errors.append(f"  {path_prefix}: missing required key 'secrets' (use 'secrets: []' if none)")
    elif not isinstance(val["secrets"], list):
        errors.append(f"  {path_prefix}.secrets: expected list, got {type(val['secrets']).__name__}")
    else:
        for s_idx, sec_item in enumerate(val["secrets"]):
            if not isinstance(sec_item, dict):
                errors.append(
                    f"  {path_prefix}.secrets[{s_idx}]: expected mapping with 'name' and 'account', "
                    f"got {type(sec_item).__name__}"
                )
                continue
            s_name = sec_item.get("name")
            s_account = sec_item.get("account")
            if not isinstance(s_name, str) or not s_name.strip():
                errors.append(f"  {path_prefix}.secrets[{s_idx}]: missing required field 'name'.")
            if not isinstance(s_account, str) or not s_account.strip():
                errors.append(f"  {path_prefix}.secrets[{s_idx}]: missing required field 'account'.")
            if isinstance(s_name, str) and s_name.strip() and isinstance(s_account, str) and s_account.strip():
                mapped_secret_names.add(s_name.strip())

    # 3. Hard error on unmapped required secrets
    for slot in manifest_secrets:
        if slot.required and slot.name not in mapped_secret_names:
            errors.append(
                f"  {path_prefix}: unmapped required secret '{slot.name}'. "
                f"Declare an explicit binding under 'secrets:' with both 'name' and 'account'."
            )

    return errors


def _validate_packages(data: dict[str, Any]) -> list[str]:
    """Validate packages list strictly enforcing Canonical Package Specification and explicit secrets."""
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
    app_version = get_app_version()
    agent_packages_count = 0

    for item in packages_list:
        if isinstance(item, str):
            errors.append(
                f"  packages: bare string package name '{item}' is not supported. "
                f"Use Canonical Package Specification: - {item}: {{ features: [...], config: {{...}}, secrets: [...] }}"
            )
            continue
        elif not isinstance(item, dict):
            errors.append(
                f"  packages: expected dict item following Canonical Package Specification, got {type(item).__name__} (value: {item!r})"
            )
            continue

        if len(item) != 1:
            errors.append(
                f"  packages: dictionary entry must have exactly one package name as key, got {list(item.keys())}"
            )
            continue

        pkg_name, val = next(iter(item.items()))
        if pkg_name not in available_packages:
            errors.append(
                f"  packages: unknown package '{pkg_name}'. Available packages: {', '.join(sorted(available_packages))}"
            )
            continue

        pkg_manifest = manifests[pkg_name]
        if pkg_manifest.category == "agents":
            agent_packages_count += 1

        if app_version is not None and pkg_manifest.schema_version != app_version:
            errors.append(
                f"  packages: {pkg_name}: manifest schema_version '{pkg_manifest.schema_version}' "
                f"does not match pa-container version '{app_version}'"
            )

        # Validate package component fields (config, secrets)
        pkg_comp_errors = _validate_canonical_component(
            comp_type="package",
            name=pkg_name,
            val=val,
            manifest_secrets=pkg_manifest.secrets,
            path_prefix=f"packages: {pkg_name}",
            allow_features=True,
        )
        errors.extend(pkg_comp_errors)

        if not isinstance(val, dict):
            continue

        # Validate features
        if "features" not in val:
            errors.append(f"  packages: {pkg_name}: missing required key 'features' (use 'features: []' if none)")
        else:
            feats_raw = val["features"]
            if not isinstance(feats_raw, list):
                errors.append(f"  packages: {pkg_name}.features: expected list, got {type(feats_raw).__name__}")
            else:
                known_features = set(pkg_manifest.features.keys()) if pkg_manifest.features else set()
                active_features_count = 0
                for f_idx, feat_item in enumerate(feats_raw):
                    if isinstance(feat_item, str):
                        errors.append(
                            f"  packages: {pkg_name}.features: bare string feature name '{feat_item}' is not supported. "
                            f"Use Canonical Feature Specification: - {feat_item}: {{ config: {{...}}, secrets: [...] }}"
                        )
                        continue
                    if not isinstance(feat_item, dict):
                        errors.append(
                            f"  packages: {pkg_name}.features[{f_idx}]: expected dict item following Canonical Feature Specification, "
                            f"got {type(feat_item).__name__} (value: {feat_item!r})"
                        )
                        continue
                    if len(feat_item) != 1:
                        errors.append(
                            f"  packages: {pkg_name}.features[{f_idx}]: dictionary entry must have exactly one feature name as key, "
                            f"got {list(feat_item.keys())}"
                        )
                        continue
                    feat_name, feat_val = next(iter(feat_item.items()))
                    active_features_count += 1
                    if known_features and feat_name not in known_features:
                        errors.append(
                            f"  packages: {pkg_name}: unknown feature '{feat_name}'. Available features: {', '.join(sorted(known_features))}"
                        )
                        continue
                    feat_manifest = pkg_manifest.features.get(feat_name)
                    feat_secrets = feat_manifest.secrets if feat_manifest else []
                    feat_comp_errors = _validate_canonical_component(
                        comp_type="feature",
                        name=feat_name,
                        val=feat_val,
                        manifest_secrets=feat_secrets,
                        path_prefix=f"packages: {pkg_name}.features.{feat_name}",
                        allow_features=False,
                    )
                    errors.extend(feat_comp_errors)

                if pkg_manifest.features_required and active_features_count == 0:
                    known = sorted(pkg_manifest.features.keys()) if pkg_manifest.features else []
                    errors.append(
                        f"  packages: {pkg_name}: this package requires at least one feature. "
                        f"Available: {', '.join(known)}"
                    )

    if agent_packages_count == 0:
        errors.append(
            "  packages: configuration must include at least one agent package (category: 'agents'), "
            "e.g. - agents: { features: [- pi: { config: {}, secrets: [] }], config: {}, secrets: [] }"
        )
    return errors


def _validate_package_configs(data: dict[str, Any]) -> list[str]:
    """Validate package and feature configurations and reject deprecated root-level sections."""
    errors: list[str] = []

    # Reject legacy root sections
    LEGACY_ROOT_SECTIONS = ("desktop", "nested_containers", "git", "source_control")
    for sec in LEGACY_ROOT_SECTIONS:
        if sec in data:
            errors.append(
                f"  {sec}: Legacy root-level configuration section '{sec}' is not allowed. "
                f"Package configuration must be declared in 'packages:' under the canonical package specification."
            )

    manifests = discover_packages()
    from packages.discovery import get_package_dir
    from packages.loader import load_acp_plugin

    packages_list = data.get("packages") or []
    if isinstance(packages_list, list):
        for item in packages_list:
            if isinstance(item, dict) and len(item) == 1:
                pkg_name, val = next(iter(item.items()))
                if isinstance(val, dict) and pkg_name in manifests:
                    manifest = manifests[pkg_name]
                    pkg_config = val.get("config")
                    pkg_dir = get_package_dir(manifest.name)
                    plugin = None
                    with contextlib.suppress(Exception):
                        plugin = load_acp_plugin(manifest, pkg_dir)
                    if isinstance(pkg_config, dict):
                        try:
                            if plugin is not None:
                                schema_contrib = plugin.contribute_config_schema()
                                if isinstance(schema_contrib, dict):
                                    sub_keys = schema_contrib.get("keys", {})
                                    if sub_keys:
                                        from packages.loader import deep_merge

                                        merged_pkg_config = deep_merge(manifest.config, pkg_config)
                                        sub_errors = _validate_schema(
                                            merged_pkg_config, sub_keys, f"packages.{pkg_name}.config"
                                        )
                                        errors.extend(sub_errors)
                        except Exception as e:
                            errors.append(f"  packages.{pkg_name}.config: error validating package configuration: {e}")

                    # Validate feature configs
                    feats = val.get("features") or []
                    if isinstance(feats, list):
                        for f_item in feats:
                            if isinstance(f_item, dict) and len(f_item) == 1:
                                f_name, f_val = next(iter(f_item.items()))
                                if isinstance(f_val, dict) and f_name in manifest.features:
                                    feat_manifest = manifest.features[f_name]
                                    f_config = f_val.get("config")
                                    if isinstance(f_config, dict) and plugin is not None:
                                        try:
                                            feat_schema = plugin.contribute_feature_config_schema(f_name)
                                            if isinstance(feat_schema, dict):
                                                sub_keys = feat_schema.get("keys", {})
                                                if sub_keys:
                                                    from packages.loader import deep_merge

                                                    merged_feat_config = deep_merge(feat_manifest.config, f_config)
                                                    sub_errors = _validate_schema(
                                                        merged_feat_config,
                                                        sub_keys,
                                                        f"packages.{pkg_name}.features.{f_name}.config",
                                                    )
                                                    errors.extend(sub_errors)
                                        except Exception as e:
                                            errors.append(
                                                f"  packages.{pkg_name}.features.{f_name}.config: error validating feature configuration: {e}"
                                            )

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
