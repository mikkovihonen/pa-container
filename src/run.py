from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import threading
import uuid
from contextlib import ExitStack, suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

if TYPE_CHECKING:
    from pa_packages.agents.host.base import AgentMount

    from cli import RunOptions
    from config_types import GatewayConfigItem
    from logging_driver import LogDriver

sys.dont_write_bytecode = True

from pa_packages.agents.host.registry import (
    get_agent_driver,
    resolve_selected_agent_names,
)
from pa_packages.agents.host.synthesis import load_project_models

import containers
import images
import packages.loader  # noqa: F401
import project
import volumes
from build import DEFAULT_ROOT_COMMANDS, build_agent, build_project_image, build_proxy
from config import (
    ADMIN_PASSWORD,
    LLAMA_BIN,
    LLAMA_SERVER_LOCK_DIR,
    LOGS_DIR,
    MODELS_DIR,
    PROJECT_DIR,
    PROXY_IMAGE_TAG,
    PROXY_LOCK_DIR,
    PROXY_UPSTREAM_NETWORK_ENV,
    REPO_ROOT,
    global_config,
)
from config_schema import validate_config, validate_models, validate_project_yaml
from flow_export import export_mitmweb_flows, poll_agent_container_ips, recover_dangling_flows
from logging_driver import (
    LogCategory,
    get_category_logger,
    get_log_driver,
    init_log_driver,
)
from models import Model
from network import (
    ContainerNetworkManager,
    load_project_config,
    read_agent_extras,
    read_agent_ports,
    read_default_agent,
    read_enabled_agents,
    read_flow_export_enabled,
    read_llama_config,
    read_nested_containers_config,
    read_network_config,
    read_proxy_config,
    read_read_only_pa_container,
    read_resource_limits,
    resource_limit_args,
    scan_tmpfs_paths,
    scan_volume_paths,
)
from packages import ensure_package_images
from packages.loader import load_project_plugins
from packages.plugin import ContainerRunSpec, RunContext
from runtimes import PodmanRuntime
from security import read_security_config, validate_mount_paths
from server import Server
from util import (
    EnvironmentError,
    extract_ipv4_from_ip_addr,
    handle_signal,
    run_quiet,
    validate_environment,
)

logger = get_category_logger(__name__, LogCategory.AGENT)
preflight_logger = get_category_logger("run.preflight", LogCategory.PREFLIGHT)

CONTAINER_RUNTIME: str = "podman"
RUNTIME: PodmanRuntime = PodmanRuntime(upstream_network=PROXY_UPSTREAM_NETWORK_ENV)
PROXY_UPSTREAM_NETWORK: str = RUNTIME.upstream_network


# ─── Startup validation ───────────────────────────────────────────────────────


def _init_runtime() -> None:
    """Validate environment and create the runtime instance.

    Called only from ``if __name__ == "__main__"`` so that test imports of
    this module do not trigger subprocess calls or environment checks.
    """
    if not ADMIN_PASSWORD or ADMIN_PASSWORD == "CHANGEME":
        logger.error(
            "ERROR: ADMIN_PASSWORD must be set to a non-default value in the OS keyring "
            "(uv run keyring set pa-container ADMIN_PASSWORD). "
            "Host environment variables are not accepted."
        )
        sys.exit(1)
        return

    try:
        _CONTAINER_RUNTIME = validate_environment(LLAMA_BIN)
    except EnvironmentError as e:
        logger.error(f"Environment Error: {e}")
        sys.exit(1)
        return

    global CONTAINER_RUNTIME, RUNTIME, PROXY_UPSTREAM_NETWORK
    CONTAINER_RUNTIME = _CONTAINER_RUNTIME
    RUNTIME = PodmanRuntime(upstream_network=PROXY_UPSTREAM_NETWORK_ENV)
    PROXY_UPSTREAM_NETWORK = RUNTIME.upstream_network


def process_gateway_configs(gateway_configs: list[GatewayConfigItem], pa_container_dir: Path) -> None:
    """Preflight, authenticate, and validate allowlist egress for external model gateways."""
    for gw in gateway_configs:
        gw_def = gw["gatewayDef"]
        if not gw_def.auth:
            continue
        if gw_def.auth.type == "openid":
            from auth import ensure_gateway_auth

            token = ensure_gateway_auth(gw["name"], gw_def.auth)
            var_name = gw.get("containerEnvVar") or f"{gw['name'].upper().replace('-', '_')}_TOKEN"
            os.environ[var_name] = token
        elif gw_def.auth.type == "api-key":
            from secret_store import DEFAULT_KEYRING_SERVICE, get_keyring_secret

            var_name = gw.get("containerEnvVar") or f"{gw['name'].upper().replace('-', '_')}_API_KEY"
            service = gw.get("keyringService") or DEFAULT_KEYRING_SERVICE
            account = gw.get("keyringAccount") or var_name

            token_val = get_keyring_secret(account, service=service)
            if not token_val:
                logger.error(
                    f"Gateway '{gw['name']}' requires secret '{var_name}'.\n"
                    f"Save in OS keyring: uv run keyring set {service} {account}"
                )
                sys.exit(1)
                return

            os.environ[var_name] = token_val
        elif gw_def.auth.type == "agent-native":
            continue

    containers.warn_about_gateway_allowlist(pa_container_dir, gateway_configs)


def ensure_proxy_image(runtime: str, repo_root: Path = REPO_ROOT) -> bool:
    """Ensure the proxy container image is built and current with its definition files.

    Returns True if the image was rebuilt, False if it was already current.
    """
    if not images.proxy_image_is_current(repo_root=repo_root, runtime=runtime):
        logger.info("Proxy image definition changed or missing; rebuilding proxy image...")
        build_proxy(runtime)
        return True
    return False


# ─── Main ─────────────────────────────────────────────────────────────────────


def execute_run(options: RunOptions, driver: LogDriver | None = None) -> int:
    log_drv = driver or get_log_driver() or init_log_driver(PROJECT_DIR)
    try:
        _init_runtime()
    except EnvironmentError as e:
        log_drv.fail_and_render(
            LogCategory.PREFLIGHT,
            "Environment Check Failed",
            str(e),
            hints=["Ensure podman or docker is installed and in your PATH."],
            exc=e,
            source_logger=preflight_logger,
        )
        return 1

    log_drv.start_stage(LogCategory.PREFLIGHT, "Validating configuration & security")
    try:
        pa_container_dir = project.ensure_project_config(PROJECT_DIR)
    except FileNotFoundError as e:
        config_path = PROJECT_DIR / ".pa-container" / "config.yaml"
        log_drv.fail_and_render(
            LogCategory.PREFLIGHT,
            "Missing Project Configuration",
            f"Project configuration not found at {config_path}.",
            hints=[
                "Initialize the project configuration with 'pa init'.",
                "Or configure .pa-container/config.yaml manually.",
            ],
            exc=e,
            source_logger=preflight_logger,
        )
        return 1
    except Exception as e:
        log_drv.fail_and_render(
            LogCategory.PREFLIGHT,
            "Project Configuration Error",
            str(e),
            exc=e,
            source_logger=preflight_logger,
        )
        return 1

    models_path: Path = pa_container_dir / "models.yaml"
    if not models_path.is_file():
        err = f"Config file not found: expected {models_path}"
        log_drv.fail_and_render(
            LogCategory.PREFLIGHT,
            "Missing Models Configuration",
            err,
            source_logger=preflight_logger,
        )
        return 1

    # Validate per-project config schema and version compatibility.
    config_yaml_path = pa_container_dir / "config.yaml"
    is_valid, errors, schema_version = validate_config(config_yaml_path)
    if not is_valid:
        hints = project.config_fix_hint(errors, config_yaml_path)
        log_drv.fail_and_render(
            LogCategory.PREFLIGHT,
            "Configuration Incompatible",
            "\n".join(errors),
            hints=hints,
            source_logger=preflight_logger,
        )
        return 1

    yaml_errors = validate_project_yaml(pa_container_dir)
    if yaml_errors:
        log_drv.fail_and_render(
            LogCategory.PREFLIGHT,
            "Duplicate YAML Keys",
            "\n".join(yaml_errors),
            hints=["Delete the duplicate line from config.yaml and re-run."],
            source_logger=preflight_logger,
        )
        return 1

    # Validate models schema (models.yaml).
    models_valid, models_errors = validate_models(models_path)
    if not models_valid:
        log_drv.fail_and_render(
            LogCategory.PREFLIGHT,
            f"Invalid {models_path.name}",
            "\n".join(models_errors),
            hints=[f"Update {models_path} to match the expected schema."],
            source_logger=preflight_logger,
        )
        return 1

    try:
        flow_export_enabled = read_flow_export_enabled(pa_container_dir)
        ipv6_enabled = read_network_config(pa_container_dir)["ipv6"]
        llama_cfg = read_llama_config(pa_container_dir)
        agent_extras = read_agent_extras(pa_container_dir)
        read_only_pa_container = read_read_only_pa_container(pa_container_dir)
        security_cfg = read_security_config(pa_container_dir)
    except Exception as e:
        log_drv.fail_and_render(
            LogCategory.PREFLIGHT,
            "Configuration Error",
            str(e),
            exc=e,
            source_logger=preflight_logger,
        )
        return 1

    mount_errors = validate_mount_paths(agent_extras["mounts"], security_cfg["blocked_mount_paths"])
    if mount_errors:
        log_drv.fail_and_render(
            LogCategory.SECURITY,
            "Security Policy Violation in agent.mounts",
            "\n".join(mount_errors),
            hints=["Remove forbidden host mount paths from config.yaml under agent.mounts."],
            source_logger=get_category_logger("run.security", LogCategory.SECURITY),
        )
        return 1

    container_argv = options.container_argv
    project_raw_cfg = load_project_config(pa_container_dir)
    active_pkgs = images.read_project_packages(PROJECT_DIR)
    active_plugins = load_project_plugins(PROJECT_DIR)

    ctx = RunContext(
        project_dir=PROJECT_DIR,
        options=options,
        config=project_raw_cfg,
        runtime=CONTAINER_RUNTIME,
        active_packages=active_pkgs,
    )

    for plugin in active_plugins.values():
        plugin.on_run_init(ctx)

    try:
        for plugin in active_plugins.values():
            plugin.on_preflight(ctx)
    except Exception as preflight_err:
        log_drv.fail_and_render(
            LogCategory.PREFLIGHT,
            "Preflight Check Failed",
            str(preflight_err),
            exc=preflight_err,
            source_logger=preflight_logger,
        )
        return 1

    enabled_agents = read_enabled_agents(pa_container_dir)
    default_agent = read_default_agent(pa_container_dir)
    try:
        active_agent_name, selected_agent_names = resolve_selected_agent_names(
            cli_agent=options.agent,
            enabled_agents=enabled_agents,
            default_agent=default_agent,
            multi_agent=ctx.has_mode("multi-agent"),
        )
        agent_driver = get_agent_driver(active_agent_name)
        selected_agent_drivers = [get_agent_driver(name) for name in selected_agent_names]

        driver_packages: list[str] = []
        for d in selected_agent_drivers:
            for pkg in d.required_packages:
                if pkg not in driver_packages:
                    driver_packages.append(pkg)

        pkg_privileges: dict[str, Any] = {}
        try:
            from packages import aggregate_runtime_privileges, discover_packages

            active_pkgs = images.read_project_packages(PROJECT_DIR, extra_packages=driver_packages)
            all_manifests = discover_packages()
            active_manifests = [all_manifests[p] for p in active_pkgs if p in all_manifests]
            pkg_privileges = aggregate_runtime_privileges(active_manifests)
            if pkg_privileges.get("devices"):
                agent_extras["devices"] = sorted(set(agent_extras["devices"]) | set(pkg_privileges["devices"]))
            if pkg_privileges.get("cap_add"):
                agent_extras["capabilities"] = sorted(
                    set(agent_extras["capabilities"]) | set(pkg_privileges["cap_add"])
                )
            if pkg_privileges.get("env"):
                agent_extras["env"].update(pkg_privileges["env"])
        except Exception as e:
            logger.debug(f"Could not aggregate package runtime privileges: {e}")
    except ValueError as e:
        log_drv.fail_and_render(
            LogCategory.PREFLIGHT,
            "Invalid Agent Selection",
            str(e),
            exc=e,
            source_logger=preflight_logger,
        )
        return 1

    log_drv.complete_stage()
    sessions_dir = agent_driver.get_sessions_dir(PROJECT_DIR)

    # Crash recovery: reap orphaned servers, proxies, and agent containers from prior crashed runs
    try:
        containers.sweep_orphaned_servers(LLAMA_SERVER_LOCK_DIR)
        containers.sweep_orphaned_proxies(CONTAINER_RUNTIME, PROXY_LOCK_DIR)
        containers.cleanup_orphaned_agent_containers(CONTAINER_RUNTIME)
        if flow_export_enabled:
            recover_dangling_flows(
                exports_dir=pa_container_dir / "exports",
                sessions_dir=sessions_dir,
            )
    except Exception as e:
        logger.warning(f"Error during crash recovery cleanup: {e}", exc_info=True)

    nested_cfg = read_nested_containers_config(pa_container_dir)
    if pkg_privileges.get("nested_containers"):
        nested_cfg["enabled"] = True
    if nested_cfg["enabled"] and "podman" not in active_pkgs:
        log_drv.fail_and_render(
            LogCategory.PREFLIGHT,
            "Missing Package: podman",
            (
                "The configuration has nested containers enabled ('nested_containers.enabled: true'), "
                "but the configuration is missing the 'podman' capability package that would provide this capability.\n\n"
                "To enable nested containers, add 'podman' to your packages list in .pa-container/config.yaml:\n"
                "    packages:\n"
                "        - podman"
            ),
            hints=[
                "Add 'podman' to .pa-container/config.yaml under 'packages:'.",
                "Or set 'nested_containers.enabled: false' if nested containers are not needed.",
            ],
            source_logger=preflight_logger,
        )
        return 1

    nested_ports = nested_cfg["ports"]
    if nested_cfg["enabled"]:
        logger.info(
            f"Nested containers enabled (storage={nested_cfg['storage']}, security={nested_cfg['security']}): "
            f"the agent can run its own rootless podman. Its traffic still egresses through the proxy, "
            f"but the agent container's SELinux confinement is relaxed."
        )
        containers.warn_about_registry_allowlist(pa_container_dir)
        if nested_ports["publish"]:
            taken = containers.unavailable_host_ports(nested_ports["publish"], nested_ports["expose"])
            if taken:
                holders = containers.port_holders(CONTAINER_RUNTIME, taken, project.project_key(PROJECT_DIR))
                lines = [f"Host port(s) already in use: {', '.join(str(p) for p in taken)}"]
                for port in taken:
                    holder = holders.get(port)
                    lines.append(f"  {port} → {holder}" if holder else f"  {port} → not held by a container")
                log_drv.fail_and_render(
                    LogCategory.PREFLIGHT,
                    "Host Port Collision",
                    "\n".join(lines),
                    hints=[f"Free them, or change nested_containers.ports.publish in {config_yaml_path}."],
                    source_logger=preflight_logger,
                )
                return 1
            bind = "127.0.0.1" if nested_ports["expose"] != "lan" else "all interfaces"
            logger.info(
                "Publishing nested-container ports on "
                + f"{bind}: "
                + ", ".join(f"{host}→agent {agent}" for host, agent in nested_ports["publish"])
                + ". A nested container must publish the agent-side port itself "
                + "(e.g. `podman run -p 3000:3000`) for the host port to serve anything."
            )
    elif nested_ports["publish"]:
        logger.warning(
            f"nested_containers.ports.publish lists port(s) "
            f"{', '.join(str(host) for host, _ in nested_ports['publish'])} but "
            f"nested_containers.enabled is false; nothing is published."
        )

    agent_ports = read_agent_ports(pa_container_dir)

    if agent_ports["publish"]:
        taken = containers.unavailable_host_ports(agent_ports["publish"], agent_ports["expose"])
        if taken:
            holders = containers.port_holders(CONTAINER_RUNTIME, taken, project.project_key(PROJECT_DIR))
            lines = [f"Host port(s) already in use: {', '.join(str(p) for p in taken)}"]
            for port in taken:
                holder = holders.get(port)
                lines.append(f"  {port} → {holder}" if holder else f"  {port} → not held by a container")
            log_drv.fail_and_render(
                LogCategory.PREFLIGHT,
                "Host Port Collision",
                "\n".join(lines),
                hints=[f"Free them, or change agent.ports.publish in {config_yaml_path}."],
                source_logger=preflight_logger,
            )
            return 1
        bind = "127.0.0.1" if agent_ports["expose"] != "lan" else "all interfaces"
        logger.info(
            "Publishing agent container port(s) on "
            + f"{bind}: "
            + ", ".join(f"{host}→agent {agent}" for host, agent in agent_ports["publish"])
            + "."
        )

    (
        models_data,
        server_configs,
        llama_hostnames,
        gateway_configs,
        default_model,
        _,
    ) = load_project_models(pa_container_dir)

    for agent_name in enabled_agents:
        agent_drv = get_agent_driver(agent_name)
        agent_gw_configs = [gw for gw in gateway_configs if agent_drv.is_gateway_enabled_for_agent(gw)]
        agent_drv.synthesize_config(
            server_configs=server_configs,
            gateway_configs=agent_gw_configs,
            default_model=default_model,
            project_dir=PROJECT_DIR,
        )

    process_gateway_configs(gateway_configs, pa_container_dir)

    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, handle_signal)
    if hasattr(signal, "SIGQUIT"):
        signal.signal(signal.SIGQUIT, handle_signal)

    try:
        with ExitStack() as stack:
            servers: list[Server] = []
            for item in server_configs:
                base_url = item["baseUrl"]
                container_port = urlparse(base_url).port if base_url else None

                server = Server(
                    config=item["config"],
                    models_dir=MODELS_DIR,
                    llama_bin=LLAMA_BIN,
                    lock_dir=LLAMA_SERVER_LOCK_DIR,
                    repo_root=REPO_ROOT,
                    server_id=item["name"],
                    container_port=container_port,
                    startup_timeout=llama_cfg["startup_timeout"],
                    startup_attempts=llama_cfg["startup_attempts"],
                    logs_dir=LOGS_DIR,
                )
                servers.append(server)

            run_id = uuid.uuid4().hex[:12]
            agent_container_name = f"pa-container-agent-{run_id}"
            proxy_name, network_name = project.project_scope(PROJECT_DIR)

            ensure_proxy_image(CONTAINER_RUNTIME, repo_root=REPO_ROOT)

            def _make_netmgr(portconfig: str) -> ContainerNetworkManager:
                return ContainerNetworkManager(
                    RUNTIME,
                    network_name,
                    PROXY_IMAGE_TAG,
                    proxy_name=proxy_name,
                    config_dir=pa_container_dir,
                    llama_ports=portconfig,
                    llama_hostnames=" ".join(sorted(llama_hostnames)),
                    ipv6=ipv6_enabled,
                    project_dir=PROJECT_DIR,
                    gateway_configs=gateway_configs,
                )

            log_drv.start_stage(LogCategory.SERVER, "Starting model server & network proxy")
            netmgr = containers.start_dependencies_parallel(servers, _make_netmgr, stack)
            log_drv.complete_stage()
            portconfig = netmgr.llama_ports or "[]"

            mitmweb_url = netmgr.mitmweb_url()
            if mitmweb_url:
                logger.info(f"mitmweb UI for this project: {mitmweb_url}")
                if not log_drv.quiet:
                    log_drv.console.print(
                        f"  [dim cyan][{LogCategory.NETWORK}][/dim cyan] mitmweb UI for this project: [link={mitmweb_url}]{mitmweb_url}[/link] [dim]🔗 (click to open)[/dim]"
                    )
                proxy_cfg = read_proxy_config(pa_container_dir)
                eff_open_browser = (
                    options.open_browser
                    if getattr(options, "open_browser", None) is not None
                    else (
                        (os.environ.get("PA_CONTAINER_OPEN_BROWSER", "").strip().lower() in ("true", "1", "yes", "on"))
                        if "PA_CONTAINER_OPEN_BROWSER" in os.environ
                        else (
                            proxy_cfg.get("open_browser", False)
                            or getattr(global_config.runtime, "open_browser", False)
                        )
                    )
                )
                if eff_open_browser:
                    import webbrowser

                    logger.info(f"Launching mitmweb UI in default web browser: {mitmweb_url}")
                    webbrowser.open(mitmweb_url)
            proxy_isolated_ip: str | None = None
            proxy_isolated_ip6: str | None = None
            try:
                result_ip = subprocess.run(
                    [CONTAINER_RUNTIME, "exec", proxy_name, "ip", "addr", "show", RUNTIME.proxy_isolated_interface],
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=5,
                )
                proxy_isolated_ip = extract_ipv4_from_ip_addr(result_ip.stdout)
                if proxy_isolated_ip:
                    logger.info(f"Found proxy {RUNTIME.proxy_isolated_interface} IP address: {proxy_isolated_ip}")
                if ipv6_enabled:
                    match_ip6 = re.search(r"inet6\s+([0-9a-fA-F:]+)/\d+\s+scope global", result_ip.stdout)
                    if match_ip6:
                        proxy_isolated_ip6 = match_ip6.group(1)
                        logger.info(
                            f"Found proxy {RUNTIME.proxy_isolated_interface} IPv6 address: {proxy_isolated_ip6}"
                        )
                    else:
                        logger.warning(
                            f"network.ipv6 is enabled but no global IPv6 address found on proxy "
                            f"{RUNTIME.proxy_isolated_interface}; the agent will have no IPv6 default route."
                        )
            except Exception as e:
                logger.warning(f"Could not retrieve proxy network info: {e}")

            if not proxy_isolated_ip:
                raise RuntimeError(
                    f"Could not determine proxy's {RUNTIME.proxy_isolated_interface} IP; "
                    f"the agent cannot be routed through the proxy."
                )

            if ipv6_enabled:
                netmgr.warn_if_proxy_lacks_ipv6_egress()

            # ─── Resolve agent image (shared vs. project-specific) ──────
            log_drv.start_stage(LogCategory.BUILD, "Resolving agent container image")
            agent_image_tag, is_project_specific = images.resolve_agent_image(
                PROJECT_DIR, extra_packages=driver_packages
            )
            if is_project_specific:
                label_hash = images.compute_image_hash(PROJECT_DIR, extra_packages=driver_packages)
                if label_hash is None:
                    logger.error("Failed to compute project image hash")
                    sys.exit(1)
                project_hash, _ = project.project_scope(PROJECT_DIR)
                project_path = str(PROJECT_DIR.resolve())

                orphaned = images.cleanup_orphaned_project_images(CONTAINER_RUNTIME)
                if orphaned:
                    logger.info(f"Removed {len(orphaned)} orphaned project image(s): {', '.join(orphaned)}")

                removed = images.cleanup_stale_project_images(
                    CONTAINER_RUNTIME,
                    project_hash,
                    label_hash,
                )
                if removed:
                    logger.info(f"Removed {len(removed)} stale project image(s): {', '.join(removed)}")

                newest_shared = images.newest_shared_image_time(runtime=CONTAINER_RUNTIME)
                if newest_shared is None:
                    sys.exit(1)
                shared_tag, shared_ts = newest_shared

                reason = images.project_image_build_reason(
                    PROJECT_DIR,
                    agent_image_tag,
                    label_hash,
                    shared_ts,
                    shared_tag,
                    runtime=CONTAINER_RUNTIME,
                )
                if reason is not None:
                    logger.info(f"Building project-specific agent image: {agent_image_tag} ({reason})")
                    root_commands_file = PROJECT_DIR / ".pa-container" / "dependencies" / "root" / "commands.sh"
                    if root_commands_file.exists() and root_commands_file.stat().st_size > 0:
                        root_commands_path = str(root_commands_file)
                    else:
                        root_commands_path = str(DEFAULT_ROOT_COMMANDS)
                    project_packages = images.read_project_packages(PROJECT_DIR, extra_packages=driver_packages)
                    ensure_package_images(project_packages, runtime=CONTAINER_RUNTIME, repo_root=REPO_ROOT)
                    build_project_image(
                        CONTAINER_RUNTIME,
                        root_commands_path,
                        agent_image_tag,
                        label_hash,
                        project_hash=project_hash,
                        project_path=project_path,
                        build_timestamp=images.now_iso(),
                        packages=project_packages,
                    )
                    if global_config.build.prune_dangling:
                        images.prune_dangling_images(CONTAINER_RUNTIME, purge_cache=False)
                else:
                    logger.info(f"Using cached project-specific image: {agent_image_tag}")
            else:
                agent_ts = images.get_image_build_time(agent_image_tag, runtime=CONTAINER_RUNTIME)
                newest_shared = images.newest_shared_image_time(runtime=CONTAINER_RUNTIME)
                if newest_shared is not None and agent_ts is not None:
                    shared_tag, shared_ts = newest_shared
                    if shared_ts > agent_ts:
                        logger.info(
                            f"Shared base image {shared_tag} is newer than shared agent image {agent_image_tag}; "
                            "rebuilding shared agent image..."
                        )
                        build_agent(CONTAINER_RUNTIME)
                        if global_config.build.prune_dangling:
                            images.prune_dangling_images(CONTAINER_RUNTIME, purge_cache=False)
                logger.info(f"Using shared image: {agent_image_tag}")
            log_drv.complete_stage()

            # Transient tmpfs paths (config.yaml tmpfs.paths)
            tmpfs_paths = scan_tmpfs_paths(pa_container_dir)

            # Persistent unified project shadow volume (config.yaml volumes.paths + agent shadow paths)
            volume_paths = scan_volume_paths(pa_container_dir)
            agent_shadow_paths = [p for d in selected_agent_drivers for p in d.get_shadow_paths()]
            pkg_shadow_paths = list(pkg_privileges.get("shadow_paths", []))
            shadow_destinations = sorted(set(volume_paths + agent_shadow_paths + pkg_shadow_paths))
            shadow_vol_name = volumes.project_shadow_volume_name(project.project_key(PROJECT_DIR))
            project_path_str = str(PROJECT_DIR.resolve())

            orphaned_project_vols = volumes.cleanup_orphaned_project_volumes(CONTAINER_RUNTIME)
            if orphaned_project_vols:
                logger.info(
                    f"Removed {len(orphaned_project_vols)} orphaned project volume(s): "
                    f"{', '.join(orphaned_project_vols)}"
                )

            if shadow_destinations:
                log_drv.start_stage(LogCategory.VOLUME, "Initializing workspace shadow volumes")
                volumes.ensure_project_volume(
                    CONTAINER_RUNTIME,
                    shadow_vol_name,
                    project_hash=proxy_name,
                    project_path=project_path_str,
                    subpaths=[volumes.destination_to_subpath(p) for p in shadow_destinations],
                    image=agent_image_tag,
                )
                log_drv.complete_stage()

            volume_args = [
                arg
                for dest in shadow_destinations
                for arg in RUNTIME.volume_subpath_args(
                    shadow_vol_name,
                    dest,
                    volumes.destination_to_subpath(dest),
                )
            ]

            selected_mounts: list[AgentMount] = []
            seen_mount_dests: set[str] = set()
            for d in selected_agent_drivers:
                for m in d.get_mounts(PROJECT_DIR):
                    if m.destination not in seen_mount_dests:
                        seen_mount_dests.add(m.destination)
                        selected_mounts.append(m)

            driver_mounts = [arg for m in selected_mounts for arg in m.to_run_args()]
            merged_driver_env: dict[str, str] = {}
            for d in selected_agent_drivers:
                d_gateways = [gw for gw in gateway_configs if d.is_gateway_enabled_for_agent(gw)]
                merged_driver_env.update(d.get_environment(agent_extras, gateway_configs=d_gateways))
            driver_env = [flag for k, v in merged_driver_env.items() for flag in ("--env", f"{k}={v}")]
            ctx.container_name = agent_container_name
            ctx.network_name = network_name
            ctx.proxy_url = f"http://{proxy_isolated_ip}:8080" if proxy_isolated_ip else None
            ctx.exit_stack = stack

            plugin_spec = ContainerRunSpec()
            for plugin in active_plugins.values():
                plugin.on_container_configure(plugin_spec, ctx)

            driver_mount_chown: list[str] = []
            for m in selected_mounts:
                dest_path = Path(m.destination)
                try:
                    rel = dest_path.relative_to(Path("/home/agent"))
                    curr = Path("/home/agent")
                    for part in rel.parts:
                        curr = curr / part
                        driver_mount_chown.append(str(curr))
                except ValueError:
                    driver_mount_chown.append(str(dest_path))

            chown_paths = sorted(
                set(
                    tmpfs_paths
                    + shadow_destinations
                    + ["/workspace/.pa-container/exports"]
                    + plugin_spec.chown_paths
                    + driver_mount_chown
                )
            )
            final_container_argv = agent_driver.get_command(container_argv)

            active_devices: list[str] = []
            for dev in agent_extras["devices"]:
                host_dev = dev.split(":")[0]
                if Path(host_dev).exists():
                    active_devices.append(dev)
                else:
                    logger.debug(f"Device '{dev}' does not exist on host; skipping.")

            PA_CONTAINER_cmd = [
                CONTAINER_RUNTIME,
                "run",
                "--rm",
                "--name",
                agent_container_name,
                *(["--security-opt", "no-new-privileges"] if not nested_cfg["enabled"] else []),
                "--label",
                "pa-container.type=agent",
                "--label",
                f"pa-container.project.hash={project.project_key(PROJECT_DIR)}",
                "--label",
                f"pa-container.project.name={PROJECT_DIR.name}",
                "--label",
                f"pa-container.project.path={PROJECT_DIR.resolve()}",
                *(
                    ["--label", "pa-container.mode=cli"]
                    if not any("pa-container.mode=" in arg for arg in plugin_spec.extra_run_args)
                    else []
                ),
                "--label",
                f"pa-container.launcher_pid={os.getpid()}",
                "--label",
                f"pa-container.run_id={run_id}",
                "--interactive",
                "--tty",
                *RUNTIME.agent_network_args(network_name, proxy_isolated_ip),
                *RUNTIME.ipv6_run_args(ipv6_enabled),
                "--env",
                f"IPV6_ENABLED={str(ipv6_enabled).lower()}",
                *(["--env", f"DEFAULT_ROUTE6={proxy_isolated_ip6}"] if proxy_isolated_ip6 else []),
                *RUNTIME.tmpfs_args("/home/agent/"),
                *driver_mounts,
                "--volume",
                f"{PROJECT_DIR}:/workspace",
                *(["--volume", f"{pa_container_dir}:/workspace/.pa-container:ro"] if read_only_pa_container else []),
                *RUNTIME.tmpfs_args("/workspace/.pa-container/exports"),
                *volume_args,
                *RUNTIME.port_publish_args(agent_ports),
                *plugin_spec.extra_run_args,
                *[flag for m in plugin_spec.mounts for flag in m.to_run_args()],
                *[flag for v in plugin_spec.volumes for flag in ("--volume", v)],
                *[flag for dev in plugin_spec.devices for flag in ("--device", dev)],
                *[flag for cap in plugin_spec.cap_add for flag in ("--cap-add", cap)],
                *[flag for port_str in plugin_spec.ports for flag in ("-p", port_str)],
                "--workdir",
                "/workspace",
                *[flag for path in tmpfs_paths for flag in RUNTIME.tmpfs_args(path)],
                "--env",
                f"CONTAINER_CHOWN_PATHS={':'.join(chown_paths)}",
                "--env",
                f"PA_CONTAINER_AGENT={agent_driver.name}",
                "--env",
                f"PA_CONTAINER_ENABLED_AGENTS={','.join(selected_agent_names)}",
                *driver_env,
                *[flag for k, v in plugin_spec.env.items() for flag in ("--env", f"{k}={v}")],
                "--env",
                f"LLAMA_PORTS={portconfig}",
                *(["--env", f"PA_CONTAINER_VERSION={schema_version}"] if schema_version else []),
                *[flag for k, v in agent_extras["env"].items() for flag in ("--env", f"{k}={v}")],
                *[flag for m in agent_extras["mounts"] for flag in ("--volume", m)],
                *[flag for c in agent_extras["capabilities"] for flag in ("--cap-add", c)],
                *[flag for d in active_devices for flag in ("--device", d)],
                *resource_limit_args(read_resource_limits(pa_container_dir, "agent")),
                agent_image_tag,
                *final_container_argv,
            ]

            ip_holder: dict[str, list[str]] = {}
            ip_stop = threading.Event()
            ip_thread: threading.Thread | None = None
            if flow_export_enabled:

                def _discover_agent_ips() -> None:
                    ips = poll_agent_container_ips(CONTAINER_RUNTIME, agent_container_name, ip_stop)
                    if ips:
                        ip_holder["ips"] = ips

                ip_thread = threading.Thread(target=_discover_agent_ips, daemon=True)
                ip_thread.start()

            for plugin in active_plugins.values():
                plugin.post_start(ctx)

            log_drv.start_stage(LogCategory.AGENT, "Launching container session")
            log_drv.complete_stage()

            try:
                log_drv.pause_for_interactive()
                result = subprocess.run(PA_CONTAINER_cmd)
            finally:
                log_drv.resume_after_interactive()
                run_quiet(
                    [CONTAINER_RUNTIME, "rm", "-f", agent_container_name],
                    check=False,
                    label=f"cleanup agent container {agent_container_name}",
                    logger=logger,
                )

            if flow_export_enabled:
                ip_stop.set()
                if ip_thread is not None:
                    ip_thread.join(timeout=2)
                export_mitmweb_flows(
                    sessions_dir=sessions_dir,
                    client_ips=ip_holder.get("ips"),
                    exports_dir=pa_container_dir / "exports",
                )

            return result.returncode
    except Exception as e:
        active_cat = LogCategory.AGENT
        if log_drv.active_stage is not None:
            with suppress(ValueError):
                active_cat = LogCategory(log_drv.active_stage.category)
        log_drv.fail_and_render(
            active_cat,
            "Fatal Error",
            str(e),
            exc=e,
            source_logger=get_category_logger(__name__, active_cat),
        )
        return 1
    finally:
        Model.cleanup_download_lock_dir(LLAMA_SERVER_LOCK_DIR / "model_download")


def main(argv: list[str] | None = None) -> None:
    """Entrypoint for run operations."""
    from cli import RunOptions, parse_cli_args

    args_to_parse = ["run", *(argv if argv is not None else [])]
    _, options = parse_cli_args(args_to_parse)
    if isinstance(options, RunOptions):
        ret = execute_run(options)
        if ret != 0:
            sys.exit(ret)
        return
    raise ValueError("Failed to parse run options")


if __name__ == "__main__":
    _init_runtime()
    main(sys.argv[1:])
