from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .types import ProjectGitConfig

sys.dont_write_bytecode = True

from logging_driver import LogCategory, get_category_logger
from network import load_project_config

AnyLogger = logging.Logger | logging.LoggerAdapter[Any]

logger = get_category_logger(__name__, LogCategory.AGENT)
_LOG = logging.getLogger(__name__)

REQUIRED_GITIGNORE_ENTRIES: tuple[str, ...] = (".pa-container/",)


def read_git_config(config_dir: Path | None = None) -> ProjectGitConfig:
    """Read and validate the git configuration section from project config.yaml."""
    cfg = load_project_config(config_dir)
    section = cfg.get("git")
    if not isinstance(section, dict):
        raise ValueError("Missing required 'git' configuration section in project config")
    for key in ("safe_directory", "rewrite_ssh_to_https"):
        if key not in section:
            raise ValueError(f"Missing required 'git.{key}' configuration")
        if not isinstance(section[key], bool):
            raise ValueError(f"Invalid 'git.{key}': expected bool, got {type(section[key]).__name__}")
    return {
        "safe_directory": section["safe_directory"],
        "rewrite_ssh_to_https": section["rewrite_ssh_to_https"],
    }


def get_sanitized_git_config_json(log: AnyLogger, allowlist: list[str] | None = None) -> str:
    """Extract global host git configuration as JSON, strictly filtering against safe allowlist keys."""
    sanitized_dict: dict[str, str] = {}
    url_credential_regex = re.compile(r"(https?://)[^/]+:[^/@]+@")
    allowset = {k.strip().lower() for k in allowlist} if allowlist is not None else None

    dangerous_prefixes = (
        "credential.",
        "core.sshcommand",
        "core.fsmonitor",
        "core.editor",
        "filter.",
        "diff.",
        "http.extraheader",
    )

    try:
        result = subprocess.check_output(["git", "config", "--list", "--show-origin"], text=True)
    except subprocess.CalledProcessError as e:
        log.error(f"Error running git config: {e}")
        return "{}"
    except FileNotFoundError:
        log.error("'git' command not found on host.")
        return "{}"

    for line in result.splitlines():
        try:
            pattern = r"^(.+?)\t([^=]+)=(.+)$"
            m = re.match(pattern, line)
            if m:
                origin, key, value = m.group(1), m.group(2), m.group(3)

                if origin.endswith(("/.git/config", ".git/config")) or origin == "file:.git/config":
                    continue

                key = key.strip()
                key_lower = key.lower()
                value = value.strip()

                if any(key_lower.startswith(dp) or key_lower == dp for dp in dangerous_prefixes):
                    continue

                if allowset is not None and key_lower not in allowset:
                    continue

                value = url_credential_regex.sub(r"\1", value)

                sanitized_dict[key] = value

        except Exception as e:
            log.error(f"git: {e}")
            continue

    return json.dumps(sanitized_dict)


def check_repo_gitignore(project_dir: Path) -> list[str]:
    """Check if the git repository containing project_dir ignores required pa-container paths.

    Returns a list of missing required gitignore entries, or an empty list if
    all are present or if project_dir is not in a git repository.
    """
    try:
        res = subprocess.run(
            ["git", "-C", str(project_dir), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode != 0:
            return []
        git_root = Path(res.stdout.strip())
    except Exception as e:
        _LOG.debug(f"Failed to check git root in missing_gitignore_entries: {e}")
        return []

    existing_lines: set[str] = set()
    for root in {git_root, project_dir}:
        gitignore_file = root / ".gitignore"
        if gitignore_file.is_file():
            for raw_line in gitignore_file.read_text().splitlines():
                line = raw_line.split("#", 1)[0].strip()
                if line:
                    existing_lines.add(line.strip("/"))

    missing: list[str] = []
    for entry in REQUIRED_GITIGNORE_ENTRIES:
        norm = entry.strip().strip("/")
        if norm in existing_lines:
            continue
        try:
            check = subprocess.run(
                ["git", "-C", str(project_dir), "check-ignore", "-q", entry],
                capture_output=True,
                check=False,
            )
            if check.returncode == 0:
                continue
        except Exception as e:
            _LOG.debug(f"Failed git check-ignore for '{entry}': {e}")
        if entry not in missing:
            missing.append(entry)

    return missing


def check_repo_tracked_pa_container(project_dir: Path) -> list[str]:
    """Return a list of tracked files under .pa-container in project_dir, if any."""
    try:
        res = subprocess.run(
            ["git", "-C", str(project_dir), "ls-files", ".pa-container"],
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode == 0 and res.stdout.strip():
            return [line.strip() for line in res.stdout.strip().splitlines() if line.strip()]
    except Exception as e:
        _LOG.debug(f"Failed git ls-files for .pa-container: {e}")
    return []


def warn_missing_gitignore(project_dir: Path, log: AnyLogger) -> None:
    """Log warnings if .pa-container entries are missing from .gitignore or actively tracked in git."""
    missing = check_repo_gitignore(project_dir)
    if missing:
        formatted = "\n".join(f"  {entry}" for entry in missing)
        log.warning(
            "Recommended .gitignore entries are missing from this repository:\n"
            f"{formatted}\n"
            "Add them to .gitignore to prevent committing workspace configuration, credentials, or session history."
        )

    tracked = check_repo_tracked_pa_container(project_dir)
    if tracked:
        log.warning(
            f".pa-container files are currently tracked in this git repository ({len(tracked)} files found, e.g. {tracked[0]}).\n"
            "Run 'git rm -r --cached .pa-container' to untrack them so local changes and credentials are not committed."
        )


def resolve_git_hooks_mounts(project_dir: Path, read_only_hooks: bool = True) -> list[str]:
    """Resolve volume mounts to lock git hooks and worktrees read-only inside container workspace."""
    git_entry = project_dir / ".git"
    git_hooks_mount: list[str] = []
    if read_only_hooks:
        if git_entry.is_dir():
            git_hooks_dir = git_entry / "hooks"
            git_hooks_dir.mkdir(parents=True, exist_ok=True)
            git_hooks_mount = ["--volume", f"{git_hooks_dir}:/workspace/.git/hooks:ro"]
        elif git_entry.is_file():
            # Git worktree or submodule: protect the .git pointer file from tampering
            git_hooks_mount = ["--volume", f"{git_entry}:/workspace/.git:ro"]
            try:
                resolved_hooks = subprocess.check_output(
                    ["git", "rev-parse", "--git-path", "hooks"],
                    cwd=str(project_dir),
                    text=True,
                    stderr=subprocess.DEVNULL,
                ).strip()
                resolved_hooks_path = Path(resolved_hooks)
                if not resolved_hooks_path.is_absolute():
                    resolved_hooks_path = project_dir / resolved_hooks_path
                if resolved_hooks_path.exists():
                    try:
                        rel = resolved_hooks_path.relative_to(project_dir.resolve())
                        git_hooks_mount.append("--volume")
                        git_hooks_mount.append(f"{resolved_hooks}:/workspace/{rel}:ro")
                    except ValueError:
                        pass
            except (subprocess.CalledProcessError, FileNotFoundError) as e:
                logger.warning(f"Could not resolve git worktree hooks path: {e}")
    return git_hooks_mount
