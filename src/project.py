import hashlib
import os
import shutil
import sys
from pathlib import Path

sys.dont_write_bytecode = True

from config_schema import SCHEMA_VERSION_MISMATCH
from logging_driver import LogCategory, get_category_logger

logger = get_category_logger(__name__, LogCategory.PREFLIGHT)

SCRIPT_DIR: Path = Path(__file__).resolve().parent
REPO_ROOT: Path = SCRIPT_DIR.parent
PROJECT_DIR: Path = Path(os.environ.get("PROJECT_DIR", Path.cwd()))

_PROJECT_CONFIG_FILES = ("config.yaml", "allowlist.yaml", "token_replacer.yaml", "models.yaml")


def project_key(project_dir: Path) -> str:
    """Return a 10-character sha256 hash identifying a workspace path."""
    return hashlib.sha256(str(project_dir.resolve()).encode()).hexdigest()[:10]


def get_project_state_dir(project_dir: Path) -> Path:
    """Return ~/.local/state/pa-container/projects/{name}-{key} or $XDG_STATE_HOME override."""
    state_home = os.environ.get("XDG_STATE_HOME")
    base_dir = Path(state_home) if state_home else Path.home() / ".local" / "state"
    key = project_key(project_dir)
    slug = f"{project_dir.resolve().name}-{key}"
    return base_dir / "pa-container" / "projects" / slug


def get_project_logs_dir(project_dir: Path) -> Path:
    """Return the logs directory for the project, creating it if absent."""
    logs_dir = get_project_state_dir(project_dir) / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir


def project_scope(project_dir: Path) -> tuple[str, str]:
    """Return ``(proxy_name, network_name)`` unique to this workspace."""
    key = project_key(project_dir)
    return f"pi-proxy-{key}", f"pi-isolated-net-{key}"


def init_project_config(project_dir: Path | None = None, repo_root: Path | None = None) -> Path:
    """Explicitly seed the per-project ``.pa-container`` config from the repo template.

    Seeds ``{project_dir}/.pa-container`` from ``{repo_root}/coding-agent/default/project``:
    the ``agents/`` subtree plus ``config.yaml``, ``models.yaml``, and the proxy
    addon configs ``allowlist.yaml``/``token_replacer.yaml``. Also seeds dependency command
    templates if present.

    Returns the project configuration directory (``{project_dir}/.pa-container``).
    """
    p_dir = project_dir if project_dir is not None else PROJECT_DIR
    r_root = repo_root if repo_root is not None else REPO_ROOT
    template_root = r_root / "coding-agent" / "default" / "project"
    if not template_root.is_dir():
        raise FileNotFoundError(f"Project config template not found: {template_root}")

    project_root = p_dir / ".pa-container"
    project_root.mkdir(parents=True, exist_ok=True)

    agents_template_root = template_root / "agents"
    agents_project_root = project_root / "agents"
    if agents_template_root.is_dir():
        for agent_dir in agents_template_root.iterdir():
            if agent_dir.is_dir():
                dst = agents_project_root / agent_dir.name
                if not dst.exists():
                    logger.info(f"Seeding {dst} from {agent_dir}.")
                    shutil.copytree(agent_dir, dst)

    for name in _PROJECT_CONFIG_FILES:
        src, dst = template_root / name, project_root / name
        if src.exists() and not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            logger.info(f"Seeding {dst} from {src}.")
            shutil.copy2(src, dst)

    deps_template_root = template_root / "dependencies"
    deps_project_root = project_root / "dependencies"
    if deps_template_root.is_dir():
        for cmd_dir in ("root", "agent"):
            src_dir = deps_template_root / cmd_dir
            dst_dir = deps_project_root / cmd_dir
            if src_dir.is_dir() and not dst_dir.exists():
                logger.info(f"Seeding {dst_dir} from {src_dir}.")
                shutil.copytree(src_dir, dst_dir)

    return project_root


def ensure_project_config(project_dir: Path | None = None, repo_root: Path | None = None) -> Path:
    """Verify that per-project ``.pa-container`` exists and is initialized.

    Returns the project configuration directory (``{project_dir}/.pa-container``).
    Raises FileNotFoundError if absent.
    """
    p_dir = project_dir if project_dir is not None else PROJECT_DIR
    project_root = p_dir / ".pa-container"
    config_file = project_root / "config.yaml"
    if not project_root.is_dir() or not config_file.is_file():
        raise FileNotFoundError(
            f"Project configuration not found at {config_file}. "
            "Initialize the project with 'pa init' or configure .pa-container/config.yaml."
        )

    return project_root


def config_fix_hint(errors: list[str], config_path: Path) -> list[str]:
    """Return targeted instructions for correcting schema validation errors in config.yaml."""
    version_only = bool(errors) and all(SCHEMA_VERSION_MISMATCH in e for e in errors)
    if version_only:
        return [
            f"\nFix: set schema_version in {config_path} to the version named above.",
            "  The rest of the file already validates, so nothing else has to change and your settings are kept.",
        ]
    return [
        f"\nFix: re-seed the one file whose shape changed — {config_path.name} —",
        f"  by deleting it and re-running:    rm {config_path}",
        "  Only that file is rewritten. allowlist.yaml, token_replacer.yaml, models.yaml,",
        "  and dependencies/ are left alone.",
        "  Your own edits to it are NOT merged, so note them first. Editing schema_version alone will not help:",
        "  the fields above are missing from the file, not mislabelled.",
    ]
