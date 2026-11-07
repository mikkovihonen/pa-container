#!/usr/bin/env python3
"""Validate version consistency across git tag, pyproject.toml, and seed config.

Checks:
  1. Latest git tag on HEAD (v* format) matches pyproject.toml [project] version
  2. pyproject.toml [project] version matches schema_version in
     coding-agent/default/{project,global}/config.yaml
  3. Seed configs are valid against the expected schema
     (required fields present, correct types)

This script runs in CI as a consistency gate before a release is published.
It validates the *template* seed config, not a seeded .pa-container/config.yaml
(which is checked at runtime by src/run.py).

Exit codes:
  0 - All checks pass
  1 - One or more checks failed (errors printed to stdout)

Usage:
  python .github/workflows/scripts/validate_versions.py
  # Or from the repo root:
  .github/workflows/scripts/validate_versions.py
"""

import argparse
import sys
import tomllib
from pathlib import Path
from typing import Any

# Inject the repo's src/ so we can import shared helpers.
# This CI script lives three levels deep inside .github/workflows/scripts/,
# so we walk up to the repo root and then into src/.
REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

import yaml  # noqa: E402  (must import after sys.path insertion)

from config_schema import validate_global_config
from schema_common import (
    SCHEMA,
    _validate_schema,
)
from template_paths import check_chat_template_paths
from version import get_git_tag_version
from yaml_strict import load_yaml_strict

TAG_PREFIX = "v"


# ─── Helpers ──────────────────────────────────────────────────────────────


def _info(msg: str) -> None:
    print(f"  ✓ {msg}")


def _error(msg: str) -> None:
    print(f"  ✗ {msg}")


def _check(label: str, condition: bool, detail: str = "") -> bool:
    """Print pass/fail for a single check. Returns True if passed."""
    if condition:
        _info(f"{label}: {detail}")
        return True
    else:
        _error(f"{label}: {detail}")
        return False


# ─── Version sources ────────────────────────────────────────────────────


def get_pyproject_version() -> str | None:
    """Read the version from pyproject.toml [project] version."""
    pyproject_path = REPO_ROOT / "pyproject.toml"
    if not pyproject_path.exists():
        return None
    try:
        with pyproject_path.open("rb") as f:
            data = tomllib.load(f)
        val = data.get("project", {}).get("version")
        return str(val) if val else None
    except Exception:
        return None


def get_seed_schema_version() -> str | None:
    """Read the schema_version from coding-agent/default/project/config.yaml."""
    config_path = REPO_ROOT / "coding-agent" / "default" / "project" / "config.yaml"
    if not config_path.exists():
        return None
    try:
        data = yaml.safe_load(config_path.read_text())
        val = data.get("schema_version") if isinstance(data, dict) else None
        return str(val) if val else None
    except Exception:
        return None


def get_global_seed_schema_version() -> str | None:
    """Read the schema_version from coding-agent/default/global/config.yaml."""
    config_path = REPO_ROOT / "coding-agent" / "default" / "global" / "config.yaml"
    if not config_path.exists():
        return None
    try:
        data = yaml.safe_load(config_path.read_text())
        val = data.get("schema_version") if isinstance(data, dict) else None
        return str(val) if val else None
    except Exception:
        return None


# ─── CLI ────────────────────────────────────────────────────────────────


def _parse_args() -> argparse.Namespace:
    """Parse CLI arguments.

    --new-version <version>
        Compare pyproject.toml and schema_version against this value instead
        of the latest git tag. Used by the release script (release.sh) because
        the new tag has not been created yet when validation runs.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--new-version",
        help=(
            "Target version to validate against (used by release.sh before the "
            "tag is created). Skips git-tag comparison."
        ),
    )
    return parser.parse_args()


# ─── Main validation logic ──────────────────────────────────────────────


def main() -> int:
    """Run all validation checks. Returns 0 on success, 1 on failure."""
    args = _parse_args()
    new_version = args.new_version  # may be None (normal CI usage)

    print("Validating version consistency...")
    all_pass = True

    # ── Check 1: Git tag version (skipped when --new-version is given) ───
    git_version: str | None = None
    if new_version is None:
        git_version = get_git_tag_version(REPO_ROOT)
        if git_version is None:
            print("  ⚠ No git tags found — skipping version consistency checks.")
            print("    (This is normal for forks or shallow clones without tags.)")
            print("  ✓ Proceeding with schema-only validation.")
        else:
            _info(f"Git tag version: {TAG_PREFIX}{git_version}")
    else:
        print(f"  ℹ Comparing against target version {new_version} (git tag check skipped).")

    # ── Check 2: pyproject.toml version ──────────────────────────────────
    pyproject_version = get_pyproject_version()
    if pyproject_version is None:
        _error("pyproject.toml version: not found")
        all_pass = False
    else:
        _info(f"pyproject.toml version: {pyproject_version}")

    # Check git tag matches pyproject.toml
    if git_version is not None and pyproject_version is not None:
        if git_version != pyproject_version:
            _error(
                f"Git tag vs pyproject.toml: tag is '{TAG_PREFIX}{git_version}', "
                f"pyproject.toml is '{pyproject_version}'"
            )
            all_pass = False
        else:
            _info(f"Git tag matches pyproject.toml: {TAG_PREFIX}{git_version}")
    elif new_version is not None and pyproject_version is not None:
        # Release script path: compare pyproject.toml against target version.
        if pyproject_version != new_version:
            _error(
                f"pyproject.toml vs target version: pyproject.toml is "
                f"'{pyproject_version}', target is '{new_version}'"
            )
            all_pass = False
        else:
            _info(f"pyproject.toml matches target version: {new_version}")

    # ── Check 3: schema_version in seed configs ───────────────────────────
    project_config_path = REPO_ROOT / "coding-agent" / "default" / "project" / "config.yaml"
    global_config_path = REPO_ROOT / "coding-agent" / "default" / "global" / "config.yaml"
    seed_data: dict[str, Any] | None = None

    for label, cfg_path in [
        ("Project seed config", project_config_path),
        ("Global seed config", global_config_path),
    ]:
        if not cfg_path.exists():
            _error(f"{label} not found: {cfg_path}")
            all_pass = False
            continue

        try:
            raw_cfg = load_yaml_strict(cfg_path.read_text())
            cfg_dict = raw_cfg if isinstance(raw_cfg, dict) else {}
        except yaml.YAMLError as e:
            _error(f"{label} is not valid YAML: {e}")
            all_pass = False
            continue

        if cfg_path == project_config_path:
            seed_data = cfg_dict

        schema_version = cfg_dict.get("schema_version")
        if schema_version is None:
            _error(f"schema_version: missing from {cfg_path.relative_to(REPO_ROOT)}")
            all_pass = False
        else:
            schema_version_str = str(schema_version)
            _info(f"{label} schema version: {schema_version_str}")

            if pyproject_version is not None:
                if pyproject_version != schema_version_str:
                    _error(
                        f"pyproject.toml vs {cfg_path.name}: pyproject.toml is "
                        f"'{pyproject_version}', config has '{schema_version_str}'"
                    )
                    all_pass = False
                else:
                    _info(f"pyproject.toml matches {label} schema_version: {pyproject_version}")

            if git_version is not None:
                if git_version != schema_version_str:
                    _error(
                        f"Git tag vs {label}: tag is '{TAG_PREFIX}{git_version}', "
                        f"config has '{schema_version_str}'"
                    )
                    all_pass = False
                else:
                    _info(f"Git tag matches {label} schema_version: {TAG_PREFIX}{git_version}")
            elif new_version is not None:
                if new_version != schema_version_str:
                    _error(
                        f"Target version vs {label}: target is "
                        f"'{new_version}', config has '{schema_version_str}'"
                    )
                    all_pass = False
                else:
                    _info(f"Target version matches {label} schema_version: {new_version}")

    # ── Check 4: Seed config schema validation ───────────────────────────
    if seed_data is not None:
        print()
        print("Validating project seed config schema...")
        schema_errors = _validate_schema(seed_data, SCHEMA)
        if schema_errors:
            _error(f"Project seed config schema has {len(schema_errors)} error(s):")
            for err in schema_errors:
                print(f"    {err}")
            all_pass = False
        else:
            _info("Project seed config schema: all required fields present with correct types")

    if global_config_path.exists():
        print()
        print("Validating global seed config schema...")
        is_global_valid, global_errors, _ = validate_global_config(global_config_path, repo_root=REPO_ROOT)
        if not is_global_valid:
            _error(f"Global seed config schema has {len(global_errors)} error(s):")
            for err in global_errors:
                print(f"    {err}")
            all_pass = False
        else:
            _info("Global seed config schema: valid")

    # ── Check 5: Seed directory completeness ─────────────────────────────
    seed_root = REPO_ROOT / "coding-agent" / "default"
    project_dir = seed_root / "project"
    global_dir = seed_root / "global"
    if not seed_root.exists():
        _error(f"Seed root directory not found: {seed_root}")
        all_pass = False
    else:
        print()
        print("Validating seed directory completeness...")

        _PROJECT_DIRS = ("agents", "dependencies")
        _PROJECT_FILES = (
            "config.yaml",
            "allowlist.yaml",
            "token_replacer.yaml",
            "models.yaml",
            "dependencies/root/commands.sh",
            "dependencies/agent/commands.sh",
        )
        _GLOBAL_DIRS = ("chat-templates", "models", "gateways")
        _GLOBAL_FILES = (
            "config.yaml",
            "models/Qwen3.6-35B-A3B-UD-Q6_K_XL.yaml",
            "chat-templates/Qwen3.6-35B-A3B-UD-Q6_K-XL/chat_template.jinja",
        )

        missing: list[str] = []
        for name in _PROJECT_DIRS:
            if not (project_dir / name).is_dir():
                missing.append(f"project/{name}/ (directory)")

        for name in _PROJECT_FILES:
            if not (project_dir / name).is_file():
                missing.append(f"project/{name}")

        for name in _GLOBAL_DIRS:
            if not (global_dir / name).is_dir():
                missing.append(f"global/{name}/ (directory)")

        for name in _GLOBAL_FILES:
            if not (global_dir / name).is_file():
                missing.append(f"global/{name}")

        if missing:
            _error(f"Seed directories are missing {len(missing)} expected item(s):")
            for item in missing:
                print(f"    - {item}")
            all_pass = False
        else:
            _info(
                f"Seed directories complete: global/ ({len(_GLOBAL_FILES)} files, {len(_GLOBAL_DIRS)} dirs) "
                f"and project/ ({len(_PROJECT_FILES)} files, {len(_PROJECT_DIRS)} dirs) all present"
            )

    # ── Check 6: chat-template-file path existence ───────────────────────
    print()
    print("Validating chat-template-file references...")
    qwen_model_file = global_dir / "models" / "Qwen3.6-35B-A3B-UD-Q6_K_XL.yaml"
    if not qwen_model_file.exists():
        _error(f"Default model file not found: {qwen_model_file}")
        all_pass = False
    else:
        qwen_def = yaml.safe_load(qwen_model_file.read_text())
        raw_flags = qwen_def.get("flags", []) if isinstance(qwen_def, dict) else []
        template_path_errors = check_chat_template_paths(raw_flags, REPO_ROOT)

        if template_path_errors:
            _error(f"Found {len(template_path_errors)} invalid chat-template-file reference(s):")
            for err in template_path_errors:
                print(f"    - {err}")
            all_pass = False
        else:
            _info("All --chat-template-file paths exist")

    # ── Check 7: Seed models.yaml schema validation ─────────────────────
    print()
    print("Validating seed models.yaml schema...")
    models_path = project_dir / "models.yaml"
    from config_schema import validate_models

    is_valid, models_schema_errors = validate_models(models_path)
    if not is_valid:
        _error(f"Seed models.yaml has {len(models_schema_errors)} error(s):")
        for err in models_schema_errors:
            print(f"    {err}")
        all_pass = False
    else:
        _info("Seed models.yaml: schema valid")

    # ── Summary ──────────────────────────────────────────────────────────
    print()
    if all_pass:
        print("All checks passed.")
        return 0
    else:
        print("Validation FAILED — fix the errors above and re-run.")
        print()
        if git_version is None:
            print("Tip: run 'git fetch --tags' if you suspect tags are missing.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
