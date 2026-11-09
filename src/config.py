import sys

sys.dont_write_bytecode = True

"""Shared configuration for the run orchestration.

Holds the paths, environment-derived constants and logging setup used across
``run.py`` and its collaborator modules (``models``, ``server``, ``network``).

Importing this module has no gating side effects — it does NOT validate the
environment or call ``sys.exit``. Those app-startup checks live in ``run.py`` so
the collaborator modules (and their tests) can import configuration cheaply.
"""

import logging
import os
import shutil
from pathlib import Path

# ─── Paths ──────────────────────────────────────────────────────────────────

SCRIPT_DIR: Path = Path(__file__).resolve().parent
REPO_ROOT: Path = SCRIPT_DIR.parent
PROJECT_DIR: Path = Path(os.environ.get("PROJECT_DIR", Path.cwd()))

from huggingface_hub.constants import HF_HUB_CACHE

from global_config import load_global_config
from logging_driver import LogCategory, get_category_logger
from project import get_project_logs_dir
from secret_store import get_keyring_secret

# ─── Global Configuration ───────────────────────────────────────────────────

global_config = load_global_config(repo_root=REPO_ROOT)

# ─── Logging ──────────────────────────────────────────────────────────────
# Configure the root logger once here; every module uses
# ``logging.getLogger(__name__)`` and inherits this configuration.

log_level_str = global_config.runtime.log_level.upper()
log_level = getattr(logging, log_level_str, logging.INFO)
logging.basicConfig(level=log_level, format="%(levelname)s: %(message)s")
logger = get_category_logger(__name__, LogCategory.PREFLIGHT)

# ─── Constants ──────────────────────────────────────────────────────────────

GLOBAL_CONFIG_DIR: Path = Path.home() / ".config" / "pa-container"
GLOBAL_MODELS_REGISTRY_DIR: Path = GLOBAL_CONFIG_DIR / "models"
GLOBAL_GATEWAYS_REGISTRY_DIR: Path = GLOBAL_CONFIG_DIR / "gateways"
GLOBAL_CHAT_TEMPLATES_DIR: Path = GLOBAL_CONFIG_DIR / "chat-templates"
GLOBAL_CACHE_DIR: Path = Path.home() / ".cache" / "pa-container"

PA_IMAGE_TAG: str = global_config.build.images.agent
PROXY_IMAGE_TAG: str = global_config.build.images.proxy
AGENT_BASE_IMAGE_TAG: str = global_config.build.images.base
BUILDER_IMAGE_TAG: str = AGENT_BASE_IMAGE_TAG

_cached_llama = GLOBAL_CACHE_DIR / "bin" / "llama-server"
LLAMA_BIN: str | None = (
    global_config.llama.bin
    or (str(_cached_llama) if _cached_llama.exists() and os.access(_cached_llama, os.X_OK) else None)
    or shutil.which("llama-server")
)

MODELS_DIR: Path = Path(HF_HUB_CACHE)
LLAMA_SERVER_LOCK_DIR: Path = GLOBAL_CACHE_DIR / "locks" / "servers"
PROXY_LOCK_DIR: Path = GLOBAL_CACHE_DIR / "locks" / "proxies"
LOGS_DIR: Path = get_project_logs_dir(PROJECT_DIR)
TOKENS_DIR: Path = GLOBAL_CACHE_DIR / "tokens"
if "ADMIN_PASSWORD" in os.environ:
    logger.warning("ADMIN_PASSWORD in host environment is ignored; credentials must be stored in the OS keyring.")
    del os.environ["ADMIN_PASSWORD"]
ADMIN_PASSWORD: str = get_keyring_secret("ADMIN_PASSWORD") or ""

# Optional explicit upstream network override. ``None`` means "use the runtime's
# default" ("podman"); a non-empty value forces it.
PROXY_UPSTREAM_NETWORK_ENV: str | None = (
    global_config.runtime.proxy_upstream_network if global_config.runtime.proxy_upstream_network != "podman" else None
)

# NOTE: per-project settings — IPv6, proxy DNS, mitmweb UI exposure, mitmweb flow
# export, proxy egress policy, tmpfs paths, llama-server startup tuning, container
# resource limits, and extra agent env/mounts — are read from
# ``{PROJECT_DIR}/.pa-container/config.yaml`` (see ``network.load_project_config``
# and its accessors), not environment variables.
