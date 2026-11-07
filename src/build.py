import argparse
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

from global_config import load_global_config
from util import EnvironmentError, validate_environment

logger = logging.getLogger(__name__)

# ─── Paths ───────────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent

global_config = load_global_config(repo_root=REPO_ROOT)

# ─── Logging ─────────────────────────────────────────────────────────────────
# build.py is its own entry point (build.sh) and configures the root logger
# from global configuration.

log_level_str = global_config.runtime.log_level.upper()
log_level = getattr(logging, log_level_str, logging.INFO)
logging.basicConfig(level=log_level, format="%(levelname)s: %(message)s")

_cached_llama = Path.home() / ".cache" / "pi-container" / "bin" / "llama-server"
LLAMA_BIN = (
    global_config.llama.bin
    or (str(_cached_llama) if _cached_llama.exists() and os.access(_cached_llama, os.X_OK) else None)
    or shutil.which("llama-server")
)
PI_IMAGE_TAG = global_config.build.images.agent
PROXY_IMAGE_TAG = global_config.build.images.proxy
BUILDER_IMAGE_TAG = global_config.build.images.builder

# The Containerfile unconditionally does `COPY --from=root_commands_path`, so
# every build must supply that context. Project-specific builds point it at the
# workspace's own root/commands.sh; the shared image uses this no-op default.
DEFAULT_ROOT_COMMANDS = REPO_ROOT / "coding-agent" / "default" / "project" / "dependencies" / "root" / "commands.sh"


def _run_command_with_logging(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    """Run a subprocess, logging each stdout/stderr line via logger.info.

    Merges stderr into stdout so both streams appear together in log output.
    Raises ``subprocess.CalledProcessError`` on non-zero exit.
    """
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
    if returncode != 0:
        raise subprocess.CalledProcessError(returncode, cmd)
    return result


# ─── Build-memory preflight ──────────────────────────────────────────────────
#
# The builder image compiles CPython (coding-agent-builder/build-python.sh). A
# PGO compile job peaks near 900 MiB, and the podman machine defaults to 2 GiB total
# regardless of core count — so on a busy VM the build dies minutes in with
#   gcc: fatal error: Killed signal terminated program cc1
# The build script refuses to start for that reason, but by then the build is already
# running. This check happens BEFORE the build is launched, so the answer arrives
# immediately.
#
# Thresholds mirror MIB_PER_JOB in coding-agent-builder/build-python.sh — keep
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
    val = os.environ.get("PI_MEMORY_PREFLIGHT")
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
        "  * skip the PGO build:       PYTHON_OPTIMIZE=0 ./build.sh  (~10-20% slower Python)\n"
        "  * already-cached Python:    PI_MEMORY_PREFLIGHT=0 ./build.sh  (skips this check)"
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
    Configured via build.dns in ~/.config/pi-container/config.yaml or BUILD_DNS.
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


def build_builder(runtime: str) -> None:
    """Build the base builder image containing CPython, Node.js, and container tools."""
    from datetime import UTC, datetime

    build_ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    logger.info(f"Building toolchain image ({runtime}): {BUILDER_IMAGE_TAG}")
    if os.environ.get("NODE_SOURCE", "").strip().lower() == "build":
        logger.info(
            "NODE_SOURCE=build: Node is compiled from source, which takes roughly an hour "
            "on a 9-core/8 GB podman machine (and longer on 4 GB, where it is limited to "
            "one compile job). Unset NODE_SOURCE to stage the official tarball instead."
        )
    else:
        logger.info("This compiles CPython, podman and netavark from source; expect several minutes.")
    _run_command_with_logging(
        [
            runtime,
            "build",
            "--force-rm",
            *_build_dns_args(),
            *_python_build_args(),
            *_node_build_args(),
            "--target",
            "stage",
            "--label",
            f"pi-container.build.time={build_ts}",
            "--label",
            "pi-container.type=shared",
            "--tag",
            BUILDER_IMAGE_TAG,
            "--file",
            str(REPO_ROOT / "coding-agent-builder" / "Containerfile"),
            str(REPO_ROOT),
        ],
    )


def build_tool(runtime: str, tool: str) -> None:
    """Build a specific on-demand toolchain image from the builder Containerfile."""
    from datetime import UTC, datetime

    from toolchains import (
        ON_DEMAND_TOOLS,
        compute_tool_hash,
        tool_to_image_tag,
        tool_to_stage_target,
    )

    if tool not in ON_DEMAND_TOOLS:
        raise ValueError(f"Unknown on-demand tool '{tool}'. Must be one of {', '.join(sorted(ON_DEMAND_TOOLS))}.")

    build_ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    tag = tool_to_image_tag(tool)
    target = tool_to_stage_target(tool)
    tool_hash = compute_tool_hash(tool, REPO_ROOT)

    logger.info(f"Building on-demand tool '{tool}' ({runtime}): {tag} [target: {target}]")
    _run_command_with_logging(
        [
            runtime,
            "build",
            "--force-rm",
            *_build_dns_args(),
            "--target",
            target,
            "--label",
            f"pi-container.build.time={build_ts}",
            "--label",
            "pi-container.type=tool",
            "--label",
            f"pi-container.tool={tool}",
            "--label",
            f"pi-container.hash={tool_hash}",
            "--tag",
            tag,
            "--file",
            str(REPO_ROOT / "coding-agent-builder" / "Containerfile"),
            str(REPO_ROOT),
        ],
    )


def build_proxy(runtime: str) -> None:
    """Build the mitmproxy container image for network egress inspection and rewriting."""
    from datetime import UTC, datetime

    from images import compute_proxy_image_hash

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
            f"pi-container.build.time={build_ts}",
            "--label",
            "pi-container.type=shared",
            "--label",
            f"pi-container.hash={proxy_hash}",
            "--tag",
            PROXY_IMAGE_TAG,
            "--file",
            str(REPO_ROOT / "coding-agent-proxy" / "Containerfile"),
            str(REPO_ROOT),
        ],
    )


def build_agent(runtime: str) -> None:
    """Build the shared default agent container image."""
    from datetime import UTC, datetime

    build_ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    logger.info(f"Building agent image ({runtime}): {PI_IMAGE_TAG}")
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
            f"pi-container.build.time={build_ts}",
            "--label",
            "pi-container.type=shared",
            "--tag",
            PI_IMAGE_TAG,
            "--file",
            str(REPO_ROOT / "coding-agent" / "Containerfile"),
            str(REPO_ROOT),
        ],
    )


def build_project_image(
    runtime: str,
    root_commands_path: str,
    image_tag: str,
    label_hash: str,
    project_hash: str = "",
    project_path: str = "",
    build_timestamp: str = "",
    tools: list[str] | None = None,
) -> None:
    """Build a project-specific agent image with baked-in command scripts and optional tools.

    Args:
        runtime: Container runtime (podman).
        root_commands_path: Absolute path to root/commands.sh on the host.
        image_tag: Image tag for the project-specific image
            (e.g., "pi-container-project-<hash>-<hash>.local").
        label_hash: Content hash to store in the image label for cache invalidation.
        project_hash: Project identity hash → set as pi-container.project.hash label.
        project_path: Absolute project directory path → set as pi-container.project.path label.
        build_timestamp: ISO 8601 timestamp → set as pi-container.build.time label.
        tools: Optional list of tools to enable (e.g. ["go", "rust"]).
    """
    logger.info(f"Building project-specific agent image ({runtime}): {image_tag}")
    cmd = [
        runtime,
        "build",
        "--force-rm",
        *_build_dns_args(),
        "--build-context",
        f"root_commands_path={Path(root_commands_path).parent}",
        "--build-arg",
        f"ROOT_COMMANDS_PATH={Path(root_commands_path).name}",
        "--build-arg",
        f"LABEL_HASH={label_hash}",
    ]
    tools_set = set(tools or [])
    from toolchains import (
        ON_DEMAND_TOOLS,
        tool_to_build_arg,
        tool_to_context_name,
        tool_to_image_tag,
    )

    for tool in sorted(tools_set):
        cmd += ["--build-arg", f"{tool_to_build_arg(tool)}=true"]
        if tool in ON_DEMAND_TOOLS:
            ctx_name = tool_to_context_name(tool)
            img_tag = tool_to_image_tag(tool)
            cmd += ["--build-context", f"{ctx_name}=docker-image://localhost/{img_tag}"]
    if project_hash:
        cmd += ["--build-arg", f"PROJECT_HASH={project_hash}"]
    if project_path:
        cmd += ["--build-arg", f"PROJECT_PATH={project_path}"]
    if build_timestamp:
        cmd += ["--build-arg", f"BUILD_TIMESTAMP={build_timestamp}"]
    cmd += [
        "--label",
        "pi-container.type=project",
        "--tag",
        image_tag,
        "--file",
        str(REPO_ROOT / "coding-agent" / "Containerfile"),
        str(REPO_ROOT),
    ]
    _run_command_with_logging(cmd)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments for image and tool builds."""
    parser = argparse.ArgumentParser(description="Build pi-container images and on-demand toolchains.")
    parser.add_argument(
        "--tools",
        metavar="TOOLS",
        help="Comma-separated list of on-demand tools to build (e.g. 'mold,git'), or 'all'.",
    )
    parser.add_argument(
        "--llama",
        action="store_true",
        help="Build minimal optimized host llama-server specifically for pi-container.",
    )
    parser.add_argument(
        "--llama-latest",
        "--latest",
        action="store_true",
        dest="llama_latest",
        help="Build the latest release of llama.cpp specifically for pi-container.",
    )
    parser.add_argument(
        "--llama-backend",
        metavar="BACKEND",
        default=None,
        help="Force specific llama acceleration backend ('metal', 'cuda', 'rocm', 'cpu').",
    )
    parser.add_argument(
        "--llama-tag",
        metavar="TAG",
        default=None,
        help="Override git release tag or commit for llama.cpp (e.g. 'v0.9.0', 'latest').",
    )
    parser.add_argument(
        "--no-clean",
        action="store_true",
        help="Skip cleaning build directory before compiling llama.cpp.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Clean orphaned containers, images, and build cache without building.",
    )
    parser.add_argument(
        "--no-prune",
        action="store_true",
        help="Skip automatic post-build dangling image pruning.",
    )
    parser.add_argument(
        "--cmake-arg",
        action="append",
        dest="cmake_args",
        default=[],
        help="Additional CMake flags to pass to the llama.cpp build.",
    )
    return parser.parse_known_args(argv)[0]


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    if args.clean:
        try:
            runtime = validate_environment(LLAMA_BIN)
        except EnvironmentError as e:
            logger.error(f"Environment Error: {e}")
            sys.exit(1)

        from containers import cleanup_orphaned_agent_containers
        from images import cleanup_orphaned_project_images, prune_dangling_images

        removed_containers = cleanup_orphaned_agent_containers(runtime)
        if removed_containers:
            logger.info(f"Removed {len(removed_containers)} orphaned container(s): {', '.join(removed_containers)}")

        orphaned_images = cleanup_orphaned_project_images(runtime)
        if orphaned_images:
            logger.info(f"Removed {len(orphaned_images)} orphaned project image(s): {', '.join(orphaned_images)}")

        prune_dangling_images(runtime, purge_cache=True)
        logger.info("Clean pass completed.")
        return

    if args.llama or args.llama_latest:
        from llama_build import LlamaBuildError, build_llama_server

        target_tag = "latest" if args.llama_latest else (args.llama_tag or global_config.llama.build.tag)
        try:
            built_path = build_llama_server(
                repo_url=global_config.llama.build.repo,
                tag=target_tag,
                backend=args.llama_backend or global_config.llama.build.backend,
                minimal=global_config.llama.build.minimal,
                clean=not args.no_clean,
                cmake_flags=(global_config.llama.build.cmake_flags or []) + (args.cmake_args or []),
            )
            logger.info(f"llama-server build complete: {built_path}")
            return
        except LlamaBuildError as e:
            logger.error(f"Failed to build llama-server: {e}")
            sys.exit(1)

    try:
        runtime = validate_environment(LLAMA_BIN)
        # Reject a bad NODE_SOURCE before any build starts. build_builder() would raise
        # on it too, but only after the memory preflight has run and podman has begun
        # resolving the build context — and a typo should cost nothing at all.
        _node_build_args()
    except EnvironmentError as e:
        logger.error(f"Environment Error: {e}")
        sys.exit(1)

    # Notify BEFORE launching a build that cannot finish: the toolchain image
    # compiles CPython, and an undersized/busy builder OOM-kills the compiler
    # minutes in.
    if not check_build_memory(runtime):
        sys.exit(1)

    try:
        if args.tools:
            from toolchains import AVAILABLE_TOOLS, CORE_TOOLS, ON_DEMAND_TOOLS

            if args.tools.strip().lower() == "all":
                requested = sorted(ON_DEMAND_TOOLS)
            else:
                requested = [t.strip() for t in args.tools.split(",") if t.strip()]
                for t in requested:
                    if t not in AVAILABLE_TOOLS:
                        logger.error(f"Unknown tool '{t}'. Available tools: {', '.join(sorted(AVAILABLE_TOOLS))}")
                        sys.exit(1)

            # Builder image is the foundation
            build_builder(runtime)
            for t in requested:
                if t in ON_DEMAND_TOOLS:
                    build_tool(runtime, t)
                elif t in CORE_TOOLS:
                    logger.info(f"Tool '{t}' is already included in builder baseline ({BUILDER_IMAGE_TAG}).")
            logger.info("All requested toolchains built successfully.")
            if not args.no_prune and global_config.build.prune_dangling:
                from images import prune_dangling_images

                prune_dangling_images(runtime, purge_cache=global_config.build.purge_build_cache)
            return

        # Strict dependency order, not a preference: the proxy image COPYs its CPython
        # and uv from the toolchain image, and the agent image COPYs from both. The
        # proxy used to be built first (it is the quick one, and a failure there was
        # cheaper), but that stopped being possible once it stopped carrying its own
        # interpreter.
        build_builder(runtime)
        build_proxy(runtime)
        build_agent(runtime)
        if not args.no_prune and global_config.build.prune_dangling:
            from images import prune_dangling_images

            prune_dangling_images(runtime, purge_cache=global_config.build.purge_build_cache)
    except subprocess.CalledProcessError as e:
        logger.error(f"Build failed: {e}")
        sys.exit(1)
    except FileNotFoundError:
        logger.error(
            f"Error: '{runtime}' command not found. Please ensure the container CLI is installed and in your PATH."
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
