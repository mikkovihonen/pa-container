import logging
import os
import re
import shutil
import subprocess
import sys
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from cli import BuildOptions, TestOptions
    from logging_driver import LogDriver

sys.dont_write_bytecode = True

from global_config import load_global_config
from logging_driver import LogCategory, fail_and_render, get_category_logger, get_log_driver
from packages import collect_distro_packages, ensure_package_images, get_core_packages
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
AGENT_BASE_IMAGE_TAG = global_config.build.images.base

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


def check_build_memory(
    runtime: str,
    required_mib: int | None = None,
    packages: Sequence[str] | Mapping[str, Any] | None = None,
    fatal: bool = True,
) -> bool:
    """Verify that sufficient memory is available to build capability packages."""
    val = os.environ.get("PA_MEMORY_PREFLIGHT")
    preflight_enabled = (
        (val.strip() not in ("0", "false", "no", "off")) if val is not None else global_config.build.memory_preflight
    )
    if not preflight_enabled:
        logger.debug("Build-memory preflight disabled.")
        return True

    if required_mib is not None:
        required = required_mib
    elif packages:
        from packages import discover_packages

        all_manifests = discover_packages(REPO_ROOT)
        pkg_names = list(packages.keys()) if isinstance(packages, Mapping) else list(packages)
        reqs = [
            all_manifests[p].build_memory_mib
            for p in pkg_names
            if p in all_manifests and all_manifests[p].build_memory_mib > 0
        ]
        required = max(reqs) if reqs else global_config.build.fallback_memory_preflight_mib
    else:
        required = global_config.build.fallback_memory_preflight_mib

    available = read_available_memory_mib(runtime)
    if available is None:
        logger.debug("Could not determine available build memory; proceeding.")
        return True
    if available >= required:
        logger.info(f"Build memory: {available} MiB available (need ~{required} MiB).")
        return True

    log = logger.error if fatal else logger.warning
    log(
        f"Only {available} MiB of memory is available where images are built, but the build "
        f"requires ~{required} MiB. "
        f"{'Not starting the build' if fatal else 'Continuing anyway'} — it may be OOM-killed."
    )
    log(
        "Fix one of:\n"
        "  * give the VM more memory:  podman machine stop && podman machine set --memory 4096 && podman machine start\n"
        "  * free memory in the VM:    stop containers you are not using (podman ps)\n"
        "  * skip memory preflight:    PA_MEMORY_PREFLIGHT=0 pa build"
    )
    return not fatal


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


def build_package(package_name: str, runtime: str = "podman", label: str | None = None) -> None:
    """Build a specific Agent Capability Package image."""
    from packages import build_package as pkg_build

    pkg_build(package_name, runtime=runtime, repo_root=REPO_ROOT, label=label)


def build_proxy(runtime: str, label: str | None = None) -> None:
    """Build the mitmproxy container image for network egress inspection and rewriting."""
    from datetime import UTC, datetime

    from images import compute_proxy_image_hash

    # Proxy requires core packages (e.g. python)
    core_pkgs = get_core_packages(REPO_ROOT)
    ensure_package_images(core_pkgs, runtime=runtime, repo_root=REPO_ROOT)

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


def build_agent_base(runtime: str, label: str | None = None) -> str:
    """Build the uniform base runner image from coding-agent/Containerfile."""
    from datetime import UTC, datetime

    base_tag = AGENT_BASE_IMAGE_TAG
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

    from packages import (
        package_to_image_tag,
        resolve_package_dependencies,
    )

    base_tag = build_agent_base(runtime)
    core_pkgs = get_core_packages(REPO_ROOT)
    resolved_specs = resolve_package_dependencies({p: [] for p in core_pkgs}, repo_root=REPO_ROOT)
    ensure_package_images(resolved_specs, runtime=runtime, repo_root=REPO_ROOT)

    build_ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    logger.info(f"Assembling shared agent image ({runtime}): {PA_IMAGE_TAG}")

    distro_pkgs = collect_distro_packages(resolved_specs, repo_root=REPO_ROOT)

    cf_lines = [
        f"FROM {base_tag}",
    ]
    if distro_pkgs:
        pkgs_str = " ".join(distro_pkgs)
        cf_lines.append(f"RUN microdnf install -y --nodocs {pkgs_str} && microdnf clean all")
    for pkg, feats in resolved_specs.items():
        cf_lines.append(f"COPY --from={package_to_image_tag(pkg, features=feats)} / /")
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
    label: str | None = None,
    **kwargs: Any,
) -> None:
    """Build a project-specific agent image with baked-in packages and commands.sh."""
    import tempfile

    from images import resolve_project_packages
    from packages import package_to_image_tag

    resolved_specs: dict[str, list[str]] = {}
    if project_path and Path(project_path).exists():
        resolved_specs = resolve_project_packages(
            Path(project_path),
            extra_packages=packages or kwargs.get("tools"),
            repo_root=REPO_ROOT,
            include_core=True,
        )
    else:
        raw_list = packages or kwargs.get("tools") or []
        for item in raw_list:
            if isinstance(item, str):
                if "+" in item:
                    pname, *pfeats = item.split("+")
                    resolved_specs.setdefault(pname.strip(), []).extend(f.strip() for f in pfeats if f.strip())
                else:
                    resolved_specs.setdefault(item.strip(), [])
        for cp in get_core_packages(REPO_ROOT):
            resolved_specs.setdefault(cp, [])
        from packages import resolve_package_dependencies

        resolved_specs = resolve_package_dependencies(resolved_specs, repo_root=REPO_ROOT)

    base_tag = build_agent_base(runtime)
    ensure_package_images(resolved_specs, runtime=runtime, repo_root=REPO_ROOT)

    root_cmd = Path(root_commands_path)
    logger.info(f"Assembling project-specific agent image ({runtime}): {image_tag}")

    distro_pkgs = collect_distro_packages(resolved_specs, repo_root=REPO_ROOT)

    cf_lines = [
        f"FROM {base_tag}",
    ]
    if distro_pkgs:
        pkgs_str = " ".join(distro_pkgs)
        cf_lines.append(f"RUN microdnf install -y --nodocs {pkgs_str} && microdnf clean all")
    for pkg, feats in resolved_specs.items():
        cf_lines.append(f"COPY --from={package_to_image_tag(pkg, features=feats)} / /")

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

            if not check_build_memory(runtime, packages=requested):
                return 1

            total_stages = len(requested)
            for idx, p in enumerate(requested, start=1):
                if log_drv is not None:
                    with log_drv.stage(LogCategory.BUILD, f"[{idx}/{total_stages}] Building package ({p})"):
                        pkg_build(p, runtime=runtime)
                else:
                    pkg_build(p, runtime=runtime)

            logger.info("All requested packages built successfully.")

            if getattr(options, "verify", False):
                from packages import render_verification_results, verify_packages

                if log_drv is not None:
                    with log_drv.stage(LogCategory.BUILD, f"Smoke testing {len(requested)} package(s)"):
                        results = verify_packages(requested, runtime=runtime)
                else:
                    results = verify_packages(requested, runtime=runtime)

                render_verification_results(results)
                failed = [r for r in results if not r.passed]
                if failed:
                    return 1

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


def execute_test(options: TestOptions, driver: LogDriver | None = None) -> int:
    """Execute in-container smoke test or integration test verifications for packages."""
    from packages import (
        discover_packages,
        render_verification_results,
        verify_packages,
        verify_packages_integration,
    )

    is_integration = getattr(options, "integration", False)
    test_type = "integration" if is_integration else "smoke"

    log_drv = driver or get_log_driver()
    if log_drv is not None and not log_drv.quiet and not log_drv.verbose and log_drv.console.is_terminal:
        log_drv.console.print(f"[dim]ℹ Running package {test_type} tests[/dim]")

    try:
        runtime = validate_environment(LLAMA_BIN)
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
        return 1

    avail = set(discover_packages().keys())
    raw_pkgs = getattr(options, "packages", "all") or "all"
    if raw_pkgs.strip().lower() == "all":
        target = sorted(avail)
    else:
        target = [p.strip() for p in raw_pkgs.split(",") if p.strip()]
        for p in target:
            if p not in avail:
                msg = f"Unknown package '{p}'. Available packages: {', '.join(sorted(avail))}"
                if log_drv is not None:
                    log_drv.fail_and_render(
                        LogCategory.BUILD,
                        "Unknown Package",
                        msg,
                        source_logger=logger,
                    )
                return 1

    stage_title = f"{'Integration' if is_integration else 'Smoke'} testing {len(target)} package(s)"
    table_title = f"Agent Capability Package (ACP) {'Integration' if is_integration else 'Smoke'} Test Results"

    if is_integration:
        if log_drv is not None:
            with log_drv.stage(LogCategory.BUILD, stage_title):
                results = verify_packages_integration(target, runtime=runtime)
        else:
            results = verify_packages_integration(target, runtime=runtime)
    else:
        if log_drv is not None:
            with log_drv.stage(LogCategory.BUILD, stage_title):
                results = verify_packages(target, runtime=runtime)
        else:
            results = verify_packages(target, runtime=runtime)

    render_verification_results(results, title=table_title)
    failed = [r for r in results if not r.passed]
    return 1 if failed else 0


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
