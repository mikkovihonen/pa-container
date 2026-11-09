import logging
import os
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from cli import BuildOptions
    from logging_driver import LogDriver

sys.dont_write_bytecode = True

from global_config import load_global_config
from logging_driver import LogCategory, fail_and_render, get_category_logger, get_log_driver
from packages import ensure_package_images
from util import EnvironmentError, validate_environment

logger = get_category_logger(__name__, LogCategory.BUILD)

# ─── Paths ───────────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent

global_config = load_global_config(repo_root=REPO_ROOT)

# ─── Logging ─────────────────────────────────────────────────────────────────
# build.py implements the 'build' subcommand of pa and configures the root logger
# from global configuration.

log_level_str = global_config.runtime.log_level.upper()
log_level = getattr(logging, log_level_str, logging.INFO)
logging.basicConfig(level=log_level, format="%(levelname)s: %(message)s")

_cached_llama = Path.home() / ".cache" / "pa-container" / "bin" / "llama-server"
LLAMA_BIN = (
    global_config.llama.bin
    or (str(_cached_llama) if _cached_llama.exists() and os.access(_cached_llama, os.X_OK) else None)
    or shutil.which("llama-server")
)
PA_IMAGE_TAG = global_config.build.images.agent
PROXY_IMAGE_TAG = global_config.build.images.proxy
BUILDER_IMAGE_TAG = global_config.build.images.builder

# The Containerfile unconditionally does `COPY --from=root_commands_path`, so
# every build must supply that context. Project-specific builds point it at the
# workspace's own root/commands.sh; the shared image uses this no-op default.
DEFAULT_ROOT_COMMANDS = REPO_ROOT / "coding-agent" / "default" / "project" / "dependencies" / "root" / "commands.sh"


def _run_command_with_logging(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    """Run a subprocess, routing through LogDriver if active or logging each line via logger.info."""
    driver = get_log_driver()
    if driver is not None:
        return driver.run_command_logged(cmd, category=LogCategory.BUILD, **kwargs)

    label = kwargs.pop("label", None)
    if label:
        logger.info(label)
    check = kwargs.pop("check", True)

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        **kwargs,
    )

    def _log_stream() -> None:
        for line in process.stdout:  # type: ignore[union-attr]
            logger.info(line.rstrip())

    thread = threading.Thread(target=_log_stream, daemon=True)
    thread.start()
    returncode = process.wait()
    thread.join()

    result: subprocess.CompletedProcess[str] = subprocess.CompletedProcess(cmd, returncode)
    if check and returncode != 0:
        raise subprocess.CalledProcessError(returncode, cmd)
    return result


# ─── Build-memory preflight ──────────────────────────────────────────────────
#
# The python package compiles CPython (packages/python/build-python.sh). A
# PGO compile job peaks near 900 MiB, and the podman machine defaults to 2 GiB total
# regardless of core count — so on a busy VM the build dies minutes in with
#   gcc: fatal error: Killed signal terminated program cc1
# The build script refuses to start for that reason, but by then the build is already
# running. This check happens BEFORE the build is launched, so the answer arrives
# immediately.
#
# Thresholds mirror MIB_PER_JOB in packages/python/build-python.sh — keep
# them in step.
_MIB_PER_JOB_PGO = 900
_MIB_PER_JOB_PLAIN = 400


def _python_optimize_enabled() -> bool:
    """Check if Python PGO profile optimization is enabled via configuration or environment."""
    if "PYTHON_OPTIMIZE" in os.environ:
        return os.environ["PYTHON_OPTIMIZE"].strip() not in ("0", "false", "no", "off")
    return global_config.build.python_optimize


def read_available_memory_mib(runtime: str) -> int | None:
    """Read available system memory in MiB on the host or inside the Podman VM."""
    local_meminfo = Path("/proc/meminfo")
    if local_meminfo.exists():
        return _parse_mem_available_mib(local_meminfo.read_text())

    try:
        result = subprocess.run(
            [runtime, "machine", "ssh", "cat /proc/meminfo"],
            capture_output=True,
            text=True,
            timeout=20,
        )
    except Exception as e:
        logger.debug(f"Could not read build-VM memory: {e}")
        return None
    if result.returncode != 0:
        logger.debug(f"Could not read build-VM memory: {result.stderr.strip()}")
        return None
    return _parse_mem_available_mib(result.stdout)


def _parse_mem_available_mib(meminfo: str) -> int | None:
    """Extract ``MemAvailable`` from /proc/meminfo text, as MiB."""
    match = re.search(r"^MemAvailable:\s+(\d+)\s*kB", meminfo, re.MULTILINE)
    return int(match.group(1)) // 1024 if match else None


def check_build_memory(runtime: str, fatal: bool = True) -> bool:
    """Verify that sufficient memory is available to compile CPython in the builder container."""
    val = os.environ.get("PA_MEMORY_PREFLIGHT")
    preflight_enabled = (
        (val.strip() not in ("0", "false", "no", "off")) if val is not None else global_config.build.memory_preflight
    )
    if not preflight_enabled:
        logger.debug("Build-memory preflight disabled.")
        return True

    required = _MIB_PER_JOB_PGO if _python_optimize_enabled() else _MIB_PER_JOB_PLAIN
    available = read_available_memory_mib(runtime)
    if available is None:
        logger.debug("Could not determine available build memory; proceeding.")
        return True
    if available >= required:
        logger.info(f"Build memory: {available} MiB available (need ~{required} MiB to compile Python).")
        return True

    log = logger.error if fatal else logger.warning
    log(
        f"Only {available} MiB of memory is available where images are built, but compiling "
        f"Python needs ~{required} MiB for a single compile job. "
        f"{'Not starting the build' if fatal else 'Continuing anyway'} — it would be OOM-killed "
        f"(gcc: fatal error: Killed signal terminated program cc1)."
    )
    log(
        "Fix one of:\n"
        "  * give the VM more memory:  podman machine stop && podman machine set --memory 4096 && podman machine start\n"
        "  * free memory in the VM:    stop containers you are not using (podman ps)\n"
        "  * skip the PGO build:       PYTHON_OPTIMIZE=0 pa build  (~10-20% slower Python)\n"
        "  * already-cached Python:    PA_MEMORY_PREFLIGHT=0 pa build  (skips this check)"
    )
    return not fatal


def _python_build_args() -> list[str]:
    """Generate ``--build-arg`` flags passing ``PYTHON_OPTIMIZE`` settings to container build."""
    value = os.environ.get("PYTHON_OPTIMIZE", "").strip()
    return ["--build-arg", f"PYTHON_OPTIMIZE={'1' if _python_optimize_enabled() else '0'}"] if value else []


_NODE_SOURCES = ("prebuilt", "build")


def _build_dns_args() -> list[str]:
    """Generate ``--dns`` flags for container build commands.

    In Podman on macOS, container builds default to gvproxy's nameserver,
    which can drop or time out on concurrent AAAA (IPv6) queries. Explicitly
    passing an upstream DNS resolver avoids transient build resolution failures.
    Configured via build.dns in ~/.config/pa-container/config.yaml or BUILD_DNS.
    Disable by setting build.dns to 'none', 'off', '0', or empty string.
    """
    dns_val = os.environ.get("BUILD_DNS") if "BUILD_DNS" in os.environ else global_config.build.dns
    dns_val = dns_val.strip() if dns_val else ""
    if not dns_val or dns_val.lower() in ("0", "none", "off", "false"):
        return []
    args: list[str] = []
    for server in dns_val.split(","):
        server = server.strip()
        if server:
            args.extend(["--dns", server])
    return args


def _node_build_args() -> list[str]:
    """Generate ``--build-arg`` flags specifying the Node.js installation source."""
    value = os.environ.get("NODE_SOURCE")
    if value is None:
        cfg_val = global_config.build.node_source
        value = cfg_val if cfg_val and cfg_val != "prebuilt" else ""
    value = value.strip().lower()
    if not value:
        return []
    if value not in _NODE_SOURCES:
        raise EnvironmentError(f"NODE_SOURCE must be one of {', '.join(_NODE_SOURCES)} (got '{value}').")
    return ["--build-arg", f"NODE_SOURCE={value}"]


CORE_PACKAGES: list[str] = ["python", "node", "podman"]
AGENT_BASE_IMAGE_TAG = "pa-container-agent-base:local"


def build_package(package_name: str, runtime: str = "podman", label: str | None = None) -> None:
    """Build a specific Agent Capability Package image."""
    from packages import build_package as pkg_build

    pkg_build(package_name, runtime=runtime, repo_root=REPO_ROOT, label=label)


def build_proxy(runtime: str, label: str | None = None) -> None:
    """Build the mitmproxy container image for network egress inspection and rewriting."""
    from datetime import UTC, datetime

    from images import compute_proxy_image_hash

    # Proxy requires python package
    ensure_package_images(["python"], runtime=runtime, repo_root=REPO_ROOT)

    build_ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    proxy_hash = compute_proxy_image_hash(REPO_ROOT)
    logger.info(f"Building proxy image ({runtime}): {PROXY_IMAGE_TAG}")
    _run_command_with_logging(
        [
            runtime,
            "build",
            "--force-rm",
            *_build_dns_args(),
            "--label",
            f"pa-container.build.time={build_ts}",
            "--label",
            "pa-container.type=shared",
            "--label",
            f"pa-container.hash={proxy_hash}",
            "--tag",
            PROXY_IMAGE_TAG,
            "--file",
            str(REPO_ROOT / "coding-agent-proxy" / "Containerfile"),
            str(REPO_ROOT),
        ],
        label=label or "Building proxy image",
    )


def build_agent_base(runtime: str, with_desktop: bool = False, label: str | None = None) -> str:
    """Build the base runner image from coding-agent/Containerfile."""
    from datetime import UTC, datetime

    base_tag = "pa-container-agent-base-desktop:local" if with_desktop else AGENT_BASE_IMAGE_TAG
    build_ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    logger.info(f"Building agent base image ({runtime}): {base_tag}")
    _run_command_with_logging(
        [
            runtime,
            "build",
            "--force-rm",
            *_build_dns_args(),
            "--build-context",
            f"root_commands_path={DEFAULT_ROOT_COMMANDS.parent}",
            "--build-arg",
            f"ROOT_COMMANDS_PATH={DEFAULT_ROOT_COMMANDS.name}",
            "--build-arg",
            f"WITH_DESKTOP={'true' if with_desktop else 'false'}",
            "--label",
            f"pa-container.build.time={build_ts}",
            "--label",
            "pa-container.type=base",
            "--tag",
            base_tag,
            "--file",
            str(REPO_ROOT / "coding-agent" / "Containerfile"),
            str(REPO_ROOT),
        ],
        label=label or f"Building agent base image ({base_tag})",
    )
    return base_tag


def build_agent(runtime: str, label: str | None = None) -> None:
    """Build the shared default agent container image with core packages."""
    import tempfile
    from datetime import UTC, datetime

    from packages import package_to_image_tag

    base_tag = build_agent_base(runtime, with_desktop=False)
    ensure_package_images(CORE_PACKAGES, runtime=runtime, repo_root=REPO_ROOT)

    build_ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    logger.info(f"Assembling shared agent image ({runtime}): {PA_IMAGE_TAG}")

    cf_lines = [
        f"FROM {base_tag}",
    ]
    for pkg in CORE_PACKAGES:
        cf_lines.append(f"COPY --from={package_to_image_tag(pkg)} / /")
    cf_lines.extend(
        [
            "WORKDIR /workspace",
            'ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]',
        ]
    )

    with tempfile.TemporaryDirectory(prefix="pa-agent-build-") as tmpdir:
        cf_path = Path(tmpdir) / "Containerfile"
        cf_path.write_text("\n".join(cf_lines) + "\n")
        _run_command_with_logging(
            [
                runtime,
                "build",
                "--force-rm",
                "--label",
                f"pa-container.build.time={build_ts}",
                "--label",
                "pa-container.type=shared",
                "--tag",
                PA_IMAGE_TAG,
                "--file",
                str(cf_path),
                str(REPO_ROOT),
            ],
            label=label or "Assembling default agent container",
        )


def build_project_image(
    runtime: str,
    root_commands_path: str,
    image_tag: str,
    label_hash: str,
    project_hash: str = "",
    project_path: str = "",
    build_timestamp: str = "",
    packages: list[str] | None = None,
    with_desktop: bool = False,
    label: str | None = None,
    **kwargs: Any,
) -> None:
    """Build a project-specific agent image with baked-in packages and commands.sh."""
    import tempfile

    from packages import package_to_image_tag

    active_packages = sorted(set(CORE_PACKAGES) | set(packages or kwargs.get("tools") or []))
    if with_desktop and "virtual-desktop" not in active_packages:
        active_packages.append("virtual-desktop")

    base_tag = build_agent_base(runtime, with_desktop=with_desktop)
    ensure_package_images(active_packages, runtime=runtime, repo_root=REPO_ROOT)

    root_cmd = Path(root_commands_path)
    logger.info(f"Assembling project-specific agent image ({runtime}): {image_tag}")

    cf_lines = [
        f"FROM {base_tag}",
    ]
    for pkg in active_packages:
        cf_lines.append(f"COPY --from={package_to_image_tag(pkg)} / /")

    cf_lines.extend(
        [
            f"COPY --from=root_commands_path {root_cmd.name} /root/commands.sh",
            "RUN chmod +x /root/commands.sh && /root/commands.sh",
            "WORKDIR /workspace",
            f'LABEL pa-container.hash="{label_hash}"',
            f'LABEL pa-container.project.hash="{project_hash}"',
            f'LABEL pa-container.project.path="{project_path}"',
            f'LABEL pa-container.build.time="{build_timestamp}"',
            'ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]',
        ]
    )

    with tempfile.TemporaryDirectory(prefix="pa-project-build-") as tmpdir:
        cf_path = Path(tmpdir) / "Containerfile"
        cf_path.write_text("\n".join(cf_lines) + "\n")
        cmd = [
            runtime,
            "build",
            "--force-rm",
            *_build_dns_args(),
            "--build-context",
            f"root_commands_path={root_cmd.parent}",
            "--tag",
            image_tag,
            "--file",
            str(cf_path),
            str(REPO_ROOT),
        ]
        _run_command_with_logging(cmd, label=label or f"Building project agent image: {image_tag}")


def run_clean_pass(purge_cache: bool = False, runtime: str | None = None) -> int:
    """Execute clean pass removing orphaned containers, images, and optionally build cache."""
    log_drv = get_log_driver()
    if log_drv is not None:
        with log_drv.stage(LogCategory.CLEANUP, "Cleaning orphaned containers & stale images"):
            return _execute_clean_pass(purge_cache=purge_cache, runtime=runtime)
    return _execute_clean_pass(purge_cache=purge_cache, runtime=runtime)


def _execute_clean_pass(purge_cache: bool = False, runtime: str | None = None) -> int:
    rt = runtime
    if rt is None:
        try:
            rt = validate_environment(LLAMA_BIN)
        except EnvironmentError as e:
            logger.error(f"Environment Error: {e}")
            return 1

    from containers import cleanup_orphaned_agent_containers
    from images import cleanup_orphaned_project_images, prune_dangling_images

    removed_containers = cleanup_orphaned_agent_containers(rt)
    if removed_containers:
        logger.info(f"Removed {len(removed_containers)} orphaned container(s): {', '.join(removed_containers)}")

    orphaned_images = cleanup_orphaned_project_images(rt)
    if orphaned_images:
        logger.info(f"Removed {len(orphaned_images)} orphaned project image(s): {', '.join(orphaned_images)}")

    prune_dangling_images(rt, purge_cache=purge_cache)
    logger.info("Clean pass completed.")
    return 0


def execute_build(options: BuildOptions, driver: LogDriver | None = None) -> int:
    """Execute image and tool builds based on structured BuildOptions."""
    log_drv = driver or get_log_driver()
    if log_drv is not None and not log_drv.quiet and not log_drv.verbose and log_drv.console.is_terminal:
        log_drv.console.print("[dim]ℹ Following build log: pa logs --build -f[/dim]")
    if options.llama or options.llama_latest:
        from llama_build import LlamaBuildError, build_llama_server

        target_tag = "latest" if options.llama_latest else (options.llama_tag or global_config.llama.build.tag)
        try:
            built_path = build_llama_server(
                repo_url=global_config.llama.build.repo,
                tag=target_tag,
                backend=options.llama_backend or global_config.llama.build.backend,
                minimal=global_config.llama.build.minimal,
                clean=not options.no_clean,
                cmake_flags=(global_config.llama.build.cmake_flags or []) + (options.cmake_args or []),
            )
            logger.info(f"llama-server build complete: {built_path}")
            return 0
        except LlamaBuildError as e:
            if log_drv is not None:
                log_drv.fail_and_render(
                    LogCategory.BUILD,
                    "LLaMA Server Build Failed",
                    str(e),
                    exc=e,
                    source_logger=logger,
                )
            else:
                fail_and_render(
                    LogCategory.BUILD,
                    "LLaMA Server Build Failed",
                    str(e),
                    exc=e,
                    source_logger=logger,
                )
            return 1
        except Exception as e:
            if log_drv is not None:
                log_drv.fail_and_render(
                    LogCategory.BUILD,
                    "LLaMA Server Build Error",
                    str(e),
                    exc=e,
                    source_logger=logger,
                )
            else:
                fail_and_render(
                    LogCategory.BUILD,
                    "LLaMA Server Build Error",
                    str(e),
                    exc=e,
                    source_logger=logger,
                )
            return 1

    try:
        runtime = validate_environment(LLAMA_BIN)
        _node_build_args()
    except EnvironmentError as e:
        if log_drv is not None:
            log_drv.fail_and_render(
                LogCategory.BUILD,
                "Environment Error",
                str(e),
                hints=["Ensure container runtime (podman/docker) is installed and available in PATH."],
                exc=e,
                source_logger=logger,
            )
        else:
            fail_and_render(
                LogCategory.BUILD,
                "Environment Error",
                str(e),
                hints=["Ensure container runtime (podman/docker) is installed and available in PATH."],
                exc=e,
                source_logger=logger,
            )
        return 1

    if log_drv is not None:
        with log_drv.stage(LogCategory.PREFLIGHT, "Verifying build memory & environment"):
            if not check_build_memory(runtime):
                return 1
    elif not check_build_memory(runtime):
        return 1

    try:
        if options.packages:
            from packages import build_package as pkg_build
            from packages import discover_packages

            avail = set(discover_packages().keys())
            if options.packages.strip().lower() == "all":
                requested = sorted(avail)
            else:
                requested = [p.strip() for p in options.packages.split(",") if p.strip()]
                for p in requested:
                    if p not in avail:
                        msg = f"Unknown package '{p}'. Available packages: {', '.join(sorted(avail))}"
                        if log_drv is not None:
                            log_drv.fail_and_render(
                                LogCategory.BUILD,
                                "Unknown Package",
                                msg,
                                source_logger=logger,
                            )
                        else:
                            fail_and_render(
                                LogCategory.BUILD,
                                "Unknown Package",
                                msg,
                                source_logger=logger,
                            )
                        return 1

            total_stages = len(requested)
            for idx, p in enumerate(requested, start=1):
                if log_drv is not None:
                    with log_drv.stage(LogCategory.BUILD, f"[{idx}/{total_stages}] Building package ({p})"):
                        pkg_build(p, runtime=runtime)
                else:
                    pkg_build(p, runtime=runtime)

            logger.info("All requested packages built successfully.")
            if not options.no_prune and global_config.build.prune_dangling:
                from images import prune_dangling_images

                if log_drv is not None:
                    with log_drv.stage(LogCategory.CLEANUP, "Pruning dangling container layers"):
                        prune_dangling_images(runtime, purge_cache=global_config.build.purge_build_cache)
                else:
                    prune_dangling_images(runtime, purge_cache=global_config.build.purge_build_cache)
            return 0

        # Build proxy and agent images
        if log_drv is not None:
            with log_drv.stage(LogCategory.BUILD, "[1/2] Building proxy image"):
                build_proxy(runtime)
            with log_drv.stage(LogCategory.BUILD, "[2/2] Building agent container"):
                build_agent(runtime)
        else:
            build_proxy(runtime)
            build_agent(runtime)

        if not options.no_prune and global_config.build.prune_dangling:
            from images import prune_dangling_images

            if log_drv is not None:
                with log_drv.stage(LogCategory.CLEANUP, "Pruning dangling container layers"):
                    prune_dangling_images(runtime, purge_cache=global_config.build.purge_build_cache)
            else:
                prune_dangling_images(runtime, purge_cache=global_config.build.purge_build_cache)
        return 0
    except subprocess.CalledProcessError as e:
        if log_drv is not None:
            log_drv.fail_and_render(
                LogCategory.BUILD,
                "Build Command Failed",
                f"Command failed with exit code {e.returncode}: {e.cmd}",
                exc=e,
                source_logger=logger,
            )
        else:
            fail_and_render(
                LogCategory.BUILD,
                "Build Command Failed",
                f"Command failed with exit code {e.returncode}: {e.cmd}",
                exc=e,
                source_logger=logger,
            )
        return 1
    except FileNotFoundError as e:
        msg = f"Error: '{runtime}' command not found. Please ensure the container CLI is installed and in your PATH."
        if log_drv is not None:
            log_drv.fail_and_render(
                LogCategory.BUILD,
                "Command Not Found",
                msg,
                exc=e,
                source_logger=logger,
            )
        else:
            fail_and_render(
                LogCategory.BUILD,
                "Command Not Found",
                msg,
                exc=e,
                source_logger=logger,
            )
        return 1
    except Exception as e:
        if log_drv is not None:
            log_drv.fail_and_render(
                LogCategory.BUILD,
                "Build Error",
                str(e),
                exc=e,
                source_logger=logger,
            )
        else:
            fail_and_render(
                LogCategory.BUILD,
                "Build Error",
                str(e),
                exc=e,
                source_logger=logger,
            )
        return 1


def parse_args(argv: list[str] | None = None) -> BuildOptions:
    """Parse command line arguments for image and tool builds using the unified CLI parser."""
    from cli import BuildOptions as Opts
    from cli import parse_cli_args

    args_to_parse = ["build", *(argv if argv is not None else [])]
    _, options = parse_cli_args(args_to_parse)
    if isinstance(options, Opts):
        return options
    raise ValueError("Failed to parse build options")


def main(argv: list[str] | None = None) -> None:
    """Entrypoint for build operations."""
    options = parse_args(argv)
    if options.clean:
        ret = run_clean_pass(purge_cache=True)
        if ret != 0:
            sys.exit(ret)
        return

    ret = execute_build(options)
    if ret != 0:
        sys.exit(ret)


if __name__ == "__main__":
    main(sys.argv[1:])
