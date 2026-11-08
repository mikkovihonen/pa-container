from __future__ import annotations

import shutil
import sys
from pathlib import Path

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

DEFAULT_GLOBAL_CONFIG_DIR: Path = Path.home() / ".config" / "pa-container"
DEFAULT_GLOBAL_CONFIG_FILE: Path = DEFAULT_GLOBAL_CONFIG_DIR / "config.yaml"


def get_repo_root() -> Path:
    """Return repository root path relative to this script."""
    return Path(__file__).resolve().parent.parent


def init_global_config(config_dir: Path | None = None, repo_root: Path | None = None) -> Path:
    """Explicitly seed global ~/.config/pa-container/config.yaml from template.

    Also ensures registry directories (models, gateways, chat-templates) exist.
    """
    target_dir = config_dir if config_dir is not None else DEFAULT_GLOBAL_CONFIG_DIR
    target_file = target_dir / "config.yaml"
    r_root = repo_root if repo_root is not None else get_repo_root()

    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "models").mkdir(parents=True, exist_ok=True)
    (target_dir / "gateways").mkdir(parents=True, exist_ok=True)
    (target_dir / "chat-templates").mkdir(parents=True, exist_ok=True)

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


def ensure_global_config(config_dir: Path | None = None, repo_root: Path | None = None) -> Path:
    """Verify that global configuration exists. Fails hard if absent."""
    target_dir = config_dir if config_dir is not None else DEFAULT_GLOBAL_CONFIG_DIR
    target_file = target_dir / "config.yaml"

    if not target_file.is_file():
        raise FileNotFoundError(
            f"Global configuration file not found at {target_file}. "
            "Initialize with 'pa init --global' or create ~/.config/pa-container/config.yaml."
        )

    return target_file


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
    raw_rt = data["runtime"]
    runtime_cfg = RuntimeGlobalConfig(
        log_level=str(raw_rt["log_level"]),
        bridge_interface=raw_rt.get("bridge_interface"),
        proxy_upstream_network=str(raw_rt["proxy_upstream_network"]),
        open_browser=bool(raw_rt["open_browser"]),
    )

    # LLaMA section
    raw_llama = data["llama"]
    raw_build = raw_llama["build"]
    cmake_flags = raw_build["cmake_flags"]

    llama_build_cfg = LlamaBuildGlobalConfig(
        repo=str(raw_build["repo"]),
        tag=str(raw_build["tag"]),
        backend=str(raw_build["backend"]),
        minimal=bool(raw_build["minimal"]),
        cmake_flags=[str(f) for f in cmake_flags],
    )

    llama_cfg = LlamaGlobalConfig(
        bin=raw_llama.get("bin"),
        build=llama_build_cfg,
    )

    # Build section
    raw_bld = data["build"]
    raw_imgs = raw_bld["images"]
    images_cfg = BuildImagesGlobalConfig(
        agent=str(raw_imgs["agent"]),
        proxy=str(raw_imgs["proxy"]),
        builder=str(raw_imgs["builder"]),
    )

    build_cfg = BuildGlobalConfig(
        images=images_cfg,
        dns=str(raw_bld["dns"]),
        python_optimize=bool(raw_bld["python_optimize"]),
        memory_preflight=bool(raw_bld["memory_preflight"]),
        node_source=str(raw_bld["node_source"]),
        prune_dangling=bool(raw_bld["prune_dangling"]),
        purge_build_cache=bool(raw_bld["purge_build_cache"]),
    )

    # Logging section
    raw_log = data["logging"]
    raw_ret = raw_log["retention"]

    logging_cfg = LoggingGlobalConfig(
        log_level=str(raw_log["log_level"]),
        retention=LogRetentionGlobalConfig(
            max_days=raw_ret["max_days"],
            max_launches=raw_ret["max_launches"],
        ),
    )

    return GlobalConfig(
        schema_version=str(schema_version or data["schema_version"]),
        runtime=runtime_cfg,
        llama=llama_cfg,
        build=build_cfg,
        logging=logging_cfg,
    )
