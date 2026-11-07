from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

from config_schema import validate_global_config
from config_types import (
    BuildGlobalConfig,
    BuildImagesGlobalConfig,
    GlobalConfig,
    LlamaBuildGlobalConfig,
    LlamaGlobalConfig,
    LoggingGlobalConfig,
    LogRetentionGlobalConfig,
    RuntimeGlobalConfig,
)
from logging_driver import LogCategory, get_category_logger
from yaml_strict import load_yaml_strict

logger = get_category_logger(__name__, LogCategory.PREFLIGHT)

DEFAULT_GLOBAL_CONFIG_DIR: Path = Path.home() / ".config" / "pi-container"
DEFAULT_GLOBAL_CONFIG_FILE: Path = DEFAULT_GLOBAL_CONFIG_DIR / "config.yaml"


def get_repo_root() -> Path:
    """Return repository root path relative to this script."""
    return Path(__file__).resolve().parent.parent


def ensure_global_config(config_dir: Path | None = None, repo_root: Path | None = None) -> Path:
    """Ensure global ~/.config/pi-container/config.yaml exists, seeding from template if absent.

    Also ensures registry directories (models, gateways, chat-templates) exist.
    """
    target_dir = config_dir if config_dir is not None else DEFAULT_GLOBAL_CONFIG_DIR
    target_file = target_dir / "config.yaml"
    r_root = repo_root if repo_root is not None else get_repo_root()

    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "models").mkdir(parents=True, exist_ok=True)
    (target_dir / "gateways").mkdir(parents=True, exist_ok=True)
    (target_dir / "chat-templates").mkdir(parents=True, exist_ok=True)

    if not target_file.exists():
        template_file = r_root / "coding-agent" / "default" / "global" / "config.yaml"
        if not template_file.is_file():
            raise FileNotFoundError(f"Global configuration template not found: {template_file}")
        logger.info(f"Seeding global configuration: {target_file} from {template_file}")
        shutil.copy2(template_file, target_file)

    try:
        from registry import seed_default_models

        seed_default_models(target_dir / "models")
    except Exception as e:
        logger.debug(f"Default model seeding skipped or deferred: {e}")

    return target_file


def _parse_bool(val: Any) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(val)
    if isinstance(val, str):
        return val.strip().lower() not in ("0", "false", "no", "off", "")
    return bool(val)


def load_global_config(config_file: Path | None = None, repo_root: Path | None = None) -> GlobalConfig:
    """Load and validate the global configuration file into a typed GlobalConfig."""
    cfg_file = config_file
    if cfg_file is None:
        target_dir = DEFAULT_GLOBAL_CONFIG_DIR
        cfg_file = ensure_global_config(config_dir=target_dir, repo_root=repo_root)
    elif not cfg_file.exists():
        ensure_global_config(config_dir=cfg_file.parent, repo_root=repo_root)

    is_valid, errors, schema_version = validate_global_config(cfg_file, repo_root=repo_root)
    if not is_valid:
        error_msg = f"Invalid global configuration at {cfg_file}:\n" + "\n".join(errors)
        raise ValueError(error_msg)

    data = load_yaml_strict(cfg_file.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"Global configuration must be a YAML mapping: {cfg_file}")

    # Runtime section
    raw_rt = data.get("runtime", {})
    runtime_cfg = RuntimeGlobalConfig(
        log_level=os.environ.get("LOG_LEVEL") or str(raw_rt.get("log_level", "INFO")),
        bridge_interface=os.environ.get("BRIDGE_INTERFACE") or raw_rt.get("bridge_interface"),
        proxy_upstream_network=os.environ.get("PROXY_UPSTREAM_NETWORK")
        or str(raw_rt.get("proxy_upstream_network", "podman")),
        open_browser=_parse_bool(os.environ.get("PI_CONTAINER_OPEN_BROWSER", raw_rt.get("open_browser", False))),
    )

    # LLaMA section
    raw_llama = data.get("llama", {})
    raw_build = raw_llama.get("build", {})
    cmake_flags = raw_build.get("cmake_flags", [])
    if not isinstance(cmake_flags, list):
        cmake_flags = []

    llama_build_cfg = LlamaBuildGlobalConfig(
        repo=os.environ.get("LLAMA_BUILD_REPO")
        or str(raw_build.get("repo", "https://github.com/ggml-org/llama.cpp.git")),
        tag=os.environ.get("LLAMA_BUILD_TAG") or str(raw_build.get("tag", "v0.9.0")),
        backend=os.environ.get("LLAMA_BUILD_BACKEND") or str(raw_build.get("backend", "auto")),
        minimal=_parse_bool(os.environ.get("LLAMA_BUILD_MINIMAL", raw_build.get("minimal", True))),
        cmake_flags=[str(f) for f in cmake_flags],
    )

    llama_bin = os.environ.get("LLAMA_BIN") or raw_llama.get("bin")
    llama_cfg = LlamaGlobalConfig(
        bin=llama_bin,
        build=llama_build_cfg,
    )

    # Build section
    raw_bld = data.get("build", {})
    raw_imgs = raw_bld.get("images", {})
    images_cfg = BuildImagesGlobalConfig(
        agent=os.environ.get("PI_IMAGE_TAG") or str(raw_imgs.get("agent", "pi-coding-agent:local")),
        proxy=os.environ.get("PROXY_IMAGE_TAG") or str(raw_imgs.get("proxy", "pi-coding-agent-proxy:local")),
        builder=os.environ.get("BUILDER_IMAGE_TAG") or str(raw_imgs.get("builder", "pi-coding-agent-builder:local")),
    )

    build_cfg = BuildGlobalConfig(
        images=images_cfg,
        dns=os.environ.get("BUILD_DNS") or str(raw_bld.get("dns", "1.1.1.1")),
        python_optimize=_parse_bool(os.environ.get("PYTHON_OPTIMIZE", raw_bld.get("python_optimize", True))),
        memory_preflight=_parse_bool(os.environ.get("PI_MEMORY_PREFLIGHT", raw_bld.get("memory_preflight", True))),
        node_source=os.environ.get("NODE_SOURCE") or str(raw_bld.get("node_source", "prebuilt")),
        prune_dangling=_parse_bool(os.environ.get("PI_PRUNE_DANGLING", raw_bld.get("prune_dangling", True))),
        purge_build_cache=_parse_bool(os.environ.get("PI_PURGE_BUILD_CACHE", raw_bld.get("purge_build_cache", False))),
    )

    # Logging section
    raw_log = data.get("logging", {})
    if not isinstance(raw_log, dict):
        raw_log = {}
    raw_ret = raw_log.get("retention", {})
    if not isinstance(raw_ret, dict):
        raw_ret = {}

    max_days_val = raw_ret.get("max_days")
    max_launches_val = raw_ret.get("max_launches")
    log_level_env = os.environ.get("LOG_LEVEL")
    log_level_str = log_level_env or raw_log.get("log_level") or raw_rt.get("log_level", "INFO")

    logging_cfg = LoggingGlobalConfig(
        log_level=str(log_level_str),
        retention=LogRetentionGlobalConfig(
            max_days=int(max_days_val) if max_days_val is not None else 14,
            max_launches=int(max_launches_val) if max_launches_val is not None else 10,
        ),
    )

    return GlobalConfig(
        schema_version=str(schema_version or data.get("schema_version", "0.6.6")),
        runtime=runtime_cfg,
        llama=llama_cfg,
        build=build_cfg,
        logging=logging_cfg,
    )
