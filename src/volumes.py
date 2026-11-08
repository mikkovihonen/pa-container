import subprocess
import sys
from pathlib import Path

from logging_driver import LogCategory, get_category_logger

sys.dont_write_bytecode = True

logger = get_category_logger(__name__, LogCategory.VOLUME)


def volume_exists(runtime: str, volume_name: str) -> bool:
    """Return True if the named volume is present in the local volume store."""
    try:
        result = subprocess.run(
            [runtime, "volume", "inspect", volume_name],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        return result.returncode == 0
    except Exception as e:
        logger.debug(f"Failed volume_exists check for '{volume_name}': {e}")
        return False


def get_volume_label(runtime: str, volume_name: str, label_key: str) -> str | None:
    """Read a label from a named volume, or None if absent/unreadable."""
    try:
        result = subprocess.run(
            [runtime, "volume", "inspect", volume_name, "--format", f'{{{{index .Labels "{label_key}"}}}}'],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        value = result.stdout.strip()
        if result.returncode == 0 and value and value != "<no value>":
            return value
        return None
    except Exception as e:
        logger.debug(f"Failed to get label '{label_key}' on volume '{volume_name}': {e}")
        return None


def remove_volume(runtime: str, volume_name: str, label_type: str = "volume") -> bool:
    """Remove a named volume. Returns True on success."""
    try:
        result = subprocess.run(
            [runtime, "volume", "rm", volume_name],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        if result.returncode == 0:
            logger.info(f"Removed {label_type}: {volume_name}")
            return True
        logger.warning(f"Could not remove {label_type} {volume_name}: {result.stderr.strip()}")
        return False
    except Exception as e:
        logger.warning(f"Could not remove {label_type} {volume_name}: {e}")
        return False


def unused_volumes(runtime: str) -> set[str] | None:
    """Return the set of volume names that are not in use by any container."""
    try:
        result = subprocess.run(
            [runtime, "volume", "ls", "--filter", "dangling=true", "--format", "{{.Name}}"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.warning(f"Could not list unused volumes to check which are in use: {e}")
        return None

    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def ensure_nested_volume(runtime: str, volume_name: str, project_hash: str, project_path: str) -> bool:
    """Create the nested-container image-store volume if it does not exist yet."""
    if volume_exists(runtime, volume_name):
        return True

    logger.info(f"Creating nested-container image store volume: {volume_name}")
    result = subprocess.run(
        [
            runtime,
            "volume",
            "create",
            "--label",
            "pa-container.type=nested-storage",
            "--label",
            f"pa-container.project.hash={project_hash}",
            "--label",
            f"pa-container.project.path={project_path}",
            volume_name,
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if result.returncode != 0:
        logger.error(
            f"Could not create nested-container volume {volume_name}: {result.stderr.strip()}. "
            f"Set nested_containers.storage: tmpfs, or disable nested_containers."
        )
        return False
    return True


def cleanup_orphaned_nested_volumes(runtime: str) -> list[str]:
    """Remove nested-storage volumes whose source project directory no longer exists."""
    removed: list[str] = []
    try:
        result = subprocess.run(
            [
                runtime,
                "volume",
                "ls",
                "--format",
                "{{.Name}}",
                "--filter",
                "label=pa-container.type=nested-storage",
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.warning(f"Could not list nested-storage volumes for orphan cleanup: {e}")
        return removed

    unused = unused_volumes(runtime)

    for name in result.stdout.strip().splitlines():
        name = name.strip()
        if not name:
            continue

        stored_path = get_volume_label(runtime, name, "pa-container.project.path")

        if stored_path is None or not stored_path.strip():
            reason = "no path label"
        elif not Path(stored_path).exists():
            reason = f"path gone: {stored_path}"
        else:
            continue

        if unused is not None and name not in unused:
            logger.info(
                f"Orphaned nested-storage volume still in use by a container, keeping for now: {name} ({reason})"
            )
            continue

        logger.info(f"Orphaned nested-storage volume ({reason}): {name}")
        if remove_volume(runtime, name):
            removed.append(name)

    return removed


def project_shadow_volume_name(project_key: str) -> str:
    """Derive the deterministic named volume name for a project's unified shadow volume."""
    return f"pi-shadow-{project_key}"


def destination_to_subpath(dest_path: str) -> str:
    """Convert a container destination path to a safe relative subpath within the shadow volume."""
    return dest_path.strip().lstrip("/")


def ensure_project_volume(
    runtime: str,
    volume_name: str,
    project_hash: str,
    project_path: str,
    subpaths: list[str] | None = None,
    image: str | None = None,
) -> bool:
    """Create a project shadow volume if it does not exist yet, and ensure subpaths exist."""
    if not volume_exists(runtime, volume_name):
        logger.info(f"Creating project shadow volume: {volume_name}")
        cmd = [
            runtime,
            "volume",
            "create",
            "--label",
            "pa-container.type=project-shadow",
            "--label",
            f"pa-container.project.hash={project_hash}",
            "--label",
            f"pa-container.project.path={project_path}",
            volume_name,
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        if result.returncode != 0:
            logger.error(f"Could not create project volume {volume_name}: {result.stderr.strip()}")
            return False

    all_subpaths = list(subpaths or [])
    if all_subpaths and image:
        mkdir_dirs = [f"/shadow/{sp}" for sp in all_subpaths if sp]
        if mkdir_dirs:
            try:
                subprocess.run(
                    [
                        runtime,
                        "run",
                        "--rm",
                        "--entrypoint",
                        "/bin/mkdir",
                        "-v",
                        f"{volume_name}:/shadow",
                        image,
                        "-p",
                        *mkdir_dirs,
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=30,
                )
            except Exception as e:
                logger.warning(f"Could not initialize shadow volume subpaths: {e}")

    return True


def cleanup_orphaned_project_volumes(runtime: str) -> list[str]:
    """Remove project shadow volumes whose source project directory no longer exists on the host."""
    removed: list[str] = []
    volume_names: set[str] = set()

    try:
        result = subprocess.run(
            [
                runtime,
                "volume",
                "ls",
                "--format",
                "{{.Name}}",
                "--filter",
                "label=pa-container.type=project-shadow",
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        for line in result.stdout.strip().splitlines():
            if line.strip():
                volume_names.add(line.strip())
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.warning(f"Could not list project-shadow volumes for orphan cleanup: {e}")

    if not volume_names:
        return removed

    unused = unused_volumes(runtime)

    for name in sorted(volume_names):
        stored_path = get_volume_label(runtime, name, "pa-container.project.path")

        if stored_path is None or not stored_path.strip():
            reason = "no path label"
        elif not Path(stored_path).exists():
            reason = f"path gone: {stored_path}"
        else:
            continue

        if unused is not None and name not in unused:
            logger.info(f"Orphaned project volume still in use by a container, keeping for now: {name} ({reason})")
            continue

        logger.info(f"Orphaned project volume ({reason}): {name}")
        if remove_volume(runtime, name, label_type="orphaned project volume"):
            removed.append(name)

    return removed
