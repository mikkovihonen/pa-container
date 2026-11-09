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
from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    from cli import RunOptions
    from config_types import GatewayConfigItem
    from logging_driver import LogDriver

sys.dont_write_bytecode = True

import containers
import images
import project
import volumes
from agents import (
    AgentMount,
    get_agent_driver,
    load_project_models,
    resolve_selected_agent_names,
)
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
from desktop import read_desktop_config, resolve_desktop_ports
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
    read_agent_extras,
    read_agent_mode,
    read_agent_ports,
    read_default_agent,
    read_enabled_agents,
    read_flow_export_enabled,
    read_git_config,
    read_llama_config,
    read_nested_containers_config,
    read_network_config,
    read_proxy_config,
    read_read_only_pa_container,
    read_resource_limits,
    resolve_t3_port,
    resource_limit_args,
    scan_tmpfs_paths,
    scan_volume_paths,
)
from runtimes import PodmanRuntime
from security import read_security_config, validate_mount_paths
from server import Server
from source_control import read_source_control_config, resolve_source_control_tokens
from util import (
    EnvironmentError,
    extract_ipv4_from_ip_addr,
    get_host_external_ip,
    get_sanitized_git_config_json,
    handle_signal,
    run_quiet,
    validate_environment,
    warn_missing_gitignore,
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

    warn_missing_gitignore(PROJECT_DIR, preflight_logger)
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
        git_cfg = read_git_config(pa_container_dir)
        sc_cfg = read_source_control_config(pa_container_dir)
        sc_tokens = resolve_source_control_tokens(pa_container_dir, log=logger)
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

    cli_agent = options.agent
    cli_t3 = options.t3
    cli_lan = options.t3_lan
    cli_t3_port = options.t3_port
    cli_t3_advertise_host = options.t3_advertise_host
    cli_t3_tunnel = options.t3_tunnel
    cli_t3_tunnel_domain = options.t3_tunnel_domain
    cli_t3_tunnel_quick = options.t3_tunnel_quick
    cli_t3_tunnel_runner = options.t3_tunnel_runner
    cli_t3_tunnel_keyring_account = options.t3_tunnel_keyring_account
    cli_t3_tunnel_tailscale_mode = options.t3_tunnel_tailscale_mode
    cli_t3_public_url = options.t3_public_url
    container_argv = options.container_argv

    if not cli_t3_tunnel:
        has_cf = bool(
            cli_t3_tunnel_quick or cli_t3_tunnel_domain or cli_t3_tunnel_runner or cli_t3_tunnel_keyring_account
        )
        has_ts = bool(cli_t3_tunnel_tailscale_mode)
        if has_cf and not has_ts:
            cli_t3_tunnel = "cloudflare"
        elif has_ts and not has_cf:
            cli_t3_tunnel = "tailscale"

    if (
        cli_t3_tunnel
        or cli_t3_port
        or cli_t3_public_url
        or cli_t3_advertise_host
        or cli_lan
        or cli_t3_tunnel_quick
        or cli_t3_tunnel_domain
        or cli_t3_tunnel_runner
        or cli_t3_tunnel_keyring_account
        or cli_t3_tunnel_tailscale_mode
    ):
        cli_t3 = True

    if (
        cli_t3_tunnel
        or cli_t3_tunnel_quick
        or cli_t3_tunnel_domain
        or cli_t3_tunnel_runner
        or cli_t3_tunnel_keyring_account
        or cli_t3_tunnel_tailscale_mode
    ):
        from tunnel import TunnelValidationError, validate_tunnel_prerequisites

        try:
            validate_tunnel_prerequisites(
                tunnel_type=cli_t3_tunnel,
                domain=cli_t3_tunnel_domain,
                quick=cli_t3_tunnel_quick,
                runner=cli_t3_tunnel_runner,
                keyring_account=cli_t3_tunnel_keyring_account,
                tailscale_mode=cli_t3_tunnel_tailscale_mode,
                runtime=CONTAINER_RUNTIME,
            )
        except TunnelValidationError as tunnel_err:
            log_drv.fail_and_render(
                LogCategory.PREFLIGHT,
                "Tunnel Prerequisites Failed",
                str(tunnel_err),
                exc=tunnel_err,
                source_logger=preflight_logger,
            )
            return 1

    is_t3_mode = cli_t3 or (read_agent_mode(pa_container_dir) == "t3")
    enabled_agents = read_enabled_agents(pa_container_dir)
    default_agent = read_default_agent(pa_container_dir)
    try:
        active_agent_name, selected_agent_names = resolve_selected_agent_names(
            cli_agent=cli_agent,
            enabled_agents=enabled_agents,
            default_agent=default_agent,
            is_t3_mode=is_t3_mode,
        )
        agent_driver = get_agent_driver(active_agent_name)
        selected_agent_drivers = [get_agent_driver(name) for name in selected_agent_names]
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

    if is_t3_mode:
        running_t3 = containers.find_running_t3_container(PROJECT_DIR, runtime=CONTAINER_RUNTIME)
        if running_t3:
            pid_info = f" (launcher PID: {running_t3.launcher_pid})" if running_t3.launcher_pid else ""
            log_drv.fail_and_render(
                LogCategory.PREFLIGHT,
                "T3 Container Already Running",
                (
                    f"A T3 mode pa-container is already running for this workspace: {running_t3.container_name}{pid_info}\n"
                    f"Only one T3 mode container can run per workspace at a time because T3 Code requires "
                    f"exclusive ownership of the workspace's T3 state."
                ),
                hints=[
                    f"To stop the existing container, run: {CONTAINER_RUNTIME} rm -f {running_t3.container_name}",
                    "Or attach to the existing T3 session in the terminal where it was started.",
                ],
                source_logger=preflight_logger,
            )
            return 1

    nested_cfg = read_nested_containers_config(pa_container_dir)
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

    is_t3_mode = cli_t3 or (read_agent_mode(pa_container_dir) == "t3")
    raw_adv_host = cli_t3_advertise_host or os.environ.get("T3_ADVERTISE_HOST") or "localhost"
    if raw_adv_host.strip().lower() in ("external", "external_ip", "auto"):
        t3_advertise_host = get_host_external_ip()
    else:
        t3_advertise_host = raw_adv_host.strip()

    agent_ports = read_agent_ports(pa_container_dir)
    if cli_lan:
        agent_ports["expose"] = "lan"

    desktop_cfg = read_desktop_config(pa_container_dir)
    desktop_novnc_port: int | None = None
    desktop_vnc_port: int | None = None
    desktop_args: list[str] = []
    gpu_args: list[str] = []
    desktop_novnc_url: str | None = None
    desktop_vnc_endpoint: str | None = None

    if desktop_cfg["enabled"]:
        desktop_novnc_port, desktop_vnc_port = resolve_desktop_ports(desktop_cfg)
        desktop_args = RUNTIME.desktop_run_args(
            desktop_cfg,
            novnc_port=desktop_novnc_port,
            vnc_port=desktop_vnc_port,
        )
        gpu_args = RUNTIME.opportunistic_gpu_args(desktop_cfg.get("gpu"))
        desktop_novnc_url = f"http://127.0.0.1:{desktop_novnc_port}/vnc.html?autoconnect=true&resize=scale"
        desktop_vnc_endpoint = f"127.0.0.1:{desktop_vnc_port}"
        logger.info(
            f"Virtual Desktop enabled ({desktop_cfg['resolution']}, {desktop_cfg['compositor']}):"
            f"\n  noVNC Web UI: {desktop_novnc_url}"
            f"\n  VNC Endpoint: {desktop_vnc_endpoint}"
        )
        if not log_drv.quiet:
            log_drv.console.print(
                f"  [dim cyan][{LogCategory.DESKTOP}][/dim cyan] Virtual Desktop: [link={desktop_novnc_url}]{desktop_novnc_url}[/link] [dim](VNC: {desktop_vnc_endpoint}) 🔗 (click to open)[/dim]"
            )

    t3_port = 3773
    if is_t3_mode:
        t3_port = resolve_t3_port(agent_ports, cli_port=cli_t3_port)
        has_active_tunnel = bool(cli_t3_tunnel or cli_t3_public_url)
        if (
            not has_active_tunnel
            and t3_advertise_host not in ("localhost", "127.0.0.1", "::1")
            and agent_ports.get("expose") != "lan"
        ):
            logger.warning(
                f"T3 Code advertised host is an external address ({t3_advertise_host}), "
                f"but agent.ports.expose is 'localhost'. Inbound connections from other devices "
                f"or external links may be refused unless agent.ports.expose is set to 'lan' in config.yaml "
                f"or --t3-lan is passed."
            )

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

    if is_t3_mode:
        t3_bind = "127.0.0.1" if agent_ports["expose"] != "lan" else "0.0.0.0"
        logger.info(
            f"T3 Code mode enabled (https://t3.codes):"
            f"\n  Inbound server port: {t3_bind}:{t3_port}"
            f"\n  Advertised host: {t3_advertise_host}"
            f"\n  Starting T3 Code server for {agent_driver.name} inside container..."
            f"\n  Once initialized, open https://t3.codes and use the pairing link displayed below."
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

    if is_t3_mode:
        from agents.t3 import synthesize_t3_policy, synthesize_t3_settings

        t3_dir = pa_container_dir / "t3"
        synthesize_t3_settings(t3_dir, agent_driver, selected_agent_drivers, project_dir=PROJECT_DIR)
        synthesize_t3_policy(t3_dir, selected_agent_drivers)

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

            t3_public_url = cli_t3_public_url
            if is_t3_mode and cli_t3_tunnel:
                ttype = cli_t3_tunnel.strip().lower()
                if ttype == "tailscale":
                    from tunnel import TailscaleTunnelManager

                    ts_mgr = TailscaleTunnelManager(mode=cli_t3_tunnel_tailscale_mode, port=t3_port)
                    pub_url, adv_host = ts_mgr.start(stack)
                    t3_public_url = t3_public_url or pub_url
                    if not cli_t3_advertise_host:
                        t3_advertise_host = adv_host
                elif ttype == "cloudflare":
                    from tunnel import CloudflareTunnelManager

                    cf_mgr = CloudflareTunnelManager(
                        domain=cli_t3_tunnel_domain,
                        quick=cli_t3_tunnel_quick,
                        runner=cli_t3_tunnel_runner,
                        keyring_account=cli_t3_tunnel_keyring_account,
                        port=t3_port,
                        runtime=CONTAINER_RUNTIME,
                        run_id=run_id,
                    )
                    pub_url, adv_host = cf_mgr.start(stack)
                    t3_public_url = t3_public_url or pub_url
                    if not cli_t3_advertise_host:
                        t3_advertise_host = adv_host

            if is_t3_mode and t3_public_url:
                from tunnel import normalize_tunnel_url

                t3_public_url = normalize_tunnel_url(t3_public_url)
                if not cli_t3_advertise_host and not cli_t3_tunnel:
                    t3_advertise_host = urlparse(t3_public_url).hostname or t3_advertise_host

                logger.info(
                    f"\n=================================================================="
                    f"\n  T3 Code Remote Access Tunnel Active"
                    f"\n  Public URL: {t3_public_url}"
                    f"\n  Protocol:   HTTPS (WSS) - Standard Port (443)"
                    f"\n=================================================================="
                )
                if not log_drv.quiet:
                    log_drv.console.print(
                        f"  [dim cyan][{LogCategory.NETWORK}][/dim cyan] T3 Tunnel URL: [link={t3_public_url}]{t3_public_url}[/link] 🔗 (click to open)"
                    )

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
            driver_tools: list[str] = []
            for d in selected_agent_drivers:
                for tool in d.required_tools:
                    if tool not in driver_tools:
                        driver_tools.append(tool)
            if is_t3_mode and "t3" not in driver_tools:
                driver_tools.append("t3")
            agent_image_tag, is_project_specific = images.resolve_agent_image(PROJECT_DIR, extra_tools=driver_tools)
            if is_project_specific:
                label_hash = images.compute_image_hash(PROJECT_DIR, extra_tools=driver_tools)
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
                    project_tools = images.read_project_tools(PROJECT_DIR, extra_tools=driver_tools)
                    images.ensure_tool_images(project_tools, CONTAINER_RUNTIME, repo_root=REPO_ROOT)
                    build_project_image(
                        CONTAINER_RUNTIME,
                        root_commands_path,
                        agent_image_tag,
                        label_hash,
                        project_hash=project_hash,
                        project_path=project_path,
                        build_timestamp=images.now_iso(),
                        tools=project_tools,
                        with_desktop=desktop_cfg["enabled"],
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

            # ─── Nested-container image store ───────────────────────────
            nested_args: list[str] = []
            if nested_cfg["enabled"]:
                project_key = project.project_key(PROJECT_DIR)
                if nested_cfg["storage"] == "volume":
                    orphaned_volumes = volumes.cleanup_orphaned_nested_volumes(CONTAINER_RUNTIME)
                    if orphaned_volumes:
                        logger.info(
                            f"Removed {len(orphaned_volumes)} orphaned nested-storage volume(s): "
                            f"{', '.join(orphaned_volumes)}"
                        )
                    if not volumes.ensure_nested_volume(
                        CONTAINER_RUNTIME,
                        RUNTIME.nested_volume_name(project_key),
                        project_hash=proxy_name,
                        project_path=str(PROJECT_DIR.resolve()),
                    ):
                        logger.warning("Falling back to a tmpfs nested image store for this run.")
                        nested_cfg = {**nested_cfg, "storage": "tmpfs"}
                nested_args = RUNTIME.nested_container_args(nested_cfg, project_key)

            # Transient tmpfs paths (config.yaml tmpfs.paths)
            tmpfs_paths = scan_tmpfs_paths(pa_container_dir)

            # Persistent unified project shadow volume (config.yaml volumes.paths + agent shadow paths)
            volume_paths = scan_volume_paths(pa_container_dir)
            agent_shadow_paths = [p for d in selected_agent_drivers for p in d.get_shadow_paths()]
            shadow_destinations = sorted(set(volume_paths + agent_shadow_paths))
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

            git_entry = PROJECT_DIR / ".git"
            git_hooks_mount: list[str] = []
            if security_cfg.get("read_only_git_hooks", True):
                if git_entry.is_dir():
                    git_hooks_dir = git_entry / "hooks"
                    git_hooks_dir.mkdir(parents=True, exist_ok=True)
                    git_hooks_mount = ["--volume", f"{git_hooks_dir}:/workspace/.git/hooks:ro"]
                elif git_entry.is_file():
                    # Git worktree or submodule: protect the .git pointer file from tampering
                    git_hooks_mount = ["--volume", f"{git_entry}:/workspace/.git:ro"]
                    try:
                        res = subprocess.run(
                            ["git", "rev-parse", "--git-path", "hooks"],
                            cwd=PROJECT_DIR,
                            capture_output=True,
                            text=True,
                            check=False,
                            timeout=5,
                        )
                        if res.returncode == 0 and res.stdout.strip():
                            raw_hooks_path = Path(res.stdout.strip())
                            resolved_hooks = (
                                raw_hooks_path
                                if raw_hooks_path.is_absolute()
                                else (PROJECT_DIR / raw_hooks_path).resolve()
                            )
                            resolved_project = PROJECT_DIR.resolve()
                            if resolved_hooks.is_relative_to(resolved_project):
                                rel = resolved_hooks.relative_to(resolved_project)
                                resolved_hooks.mkdir(parents=True, exist_ok=True)
                                git_hooks_mount.append("--volume")
                                git_hooks_mount.append(f"{resolved_hooks}:/workspace/{rel}:ro")
                    except Exception as e:
                        logger.warning(f"Could not resolve git worktree hooks path: {e}")

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
            t3_mounts: list[str] = []
            t3_chown: list[str] = []
            if is_t3_mode:
                t3_dir = pa_container_dir / "t3"
                t3_dir.mkdir(parents=True, exist_ok=True)
                t3_mounts = ["--volume", f"{t3_dir}:/home/agent/.t3"]
                shim_src = REPO_ROOT / "coding-agent" / "t3-advertise-host.cjs"
                if shim_src.exists():
                    t3_mounts.extend(["--volume", f"{shim_src}:/usr/local/share/pa-container/t3-advertise-host.cjs:ro"])
                sync_src = REPO_ROOT / "coding-agent" / "t3-sync-antigravity.py"
                if sync_src.exists():
                    t3_mounts.extend(
                        ["--volume", f"{sync_src}:/usr/local/share/pa-container/t3-sync-antigravity.py:ro"]
                    )
                policy_file = t3_dir / "policy.json"
                if policy_file.exists():
                    t3_mounts.extend(["--volume", f"{policy_file}:/etc/t3code/policy.json:ro"])
                t3_chown = ["/home/agent/.t3"]

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
                    + t3_chown
                    + driver_mount_chown
                )
            )
            final_container_argv = agent_driver.get_command(container_argv)

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
                *(["--label", "pa-container.desktop.enabled=true"] if desktop_cfg["enabled"] else []),
                "--label",
                f"pa-container.mode={'t3' if is_t3_mode else 'cli'}",
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
                *(
                    [
                        "--env",
                        "PA_CONTAINER_MODE=t3",
                        "--env",
                        f"T3_PORT={t3_port}",
                        "--env",
                        f"T3_ADVERTISE_HOST={t3_advertise_host}",
                        *(["--env", f"T3_PUBLIC_URL={t3_public_url}"] if t3_public_url else []),
                        *(["--env", "T3_LAN=true"] if agent_ports["expose"] == "lan" else []),
                    ]
                    if is_t3_mode
                    else []
                ),
                *RUNTIME.tmpfs_args("/home/agent/"),
                *driver_mounts,
                *t3_mounts,
                "--volume",
                f"{PROJECT_DIR}:/workspace",
                *(["--volume", f"{pa_container_dir}:/workspace/.pa-container:ro"] if read_only_pa_container else []),
                *git_hooks_mount,
                *RUNTIME.tmpfs_args("/workspace/.pa-container/exports"),
                *volume_args,
                *nested_args,
                *RUNTIME.nested_port_args(nested_cfg),
                *RUNTIME.port_publish_args(agent_ports),
                *desktop_args,
                *gpu_args,
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
                "--env",
                f"LLAMA_PORTS={portconfig}",
                "--env",
                f"HOST_GIT_CONFIG={get_sanitized_git_config_json(logger=logger, allowlist=security_cfg.get('git_config_allowlist'))}",
                "--env",
                f"GIT_SAFE_DIRECTORY={'true' if git_cfg['safe_directory'] else 'false'}",
                "--env",
                f"GIT_REWRITE_SSH={'true' if git_cfg['rewrite_ssh_to_https'] else 'false'}",
                "--env",
                f"SETUP_GIT_CREDENTIALS={'true' if sc_cfg['setup_git_credentials'] else 'false'}",
                *(["--env", f"PA_CONTAINER_VERSION={schema_version}"] if schema_version else []),
                *[flag for k, v in {**sc_tokens, **agent_extras["env"]}.items() for flag in ("--env", f"{k}={v}")],
                *[flag for m in agent_extras["mounts"] for flag in ("--volume", m)],
                *[flag for c in agent_extras["capabilities"] for flag in ("--cap-add", c)],
                *[flag for d in agent_extras["devices"] for flag in ("--device", d)],
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

            if desktop_cfg["enabled"] and desktop_novnc_url:
                eff_desktop_open_browser = (
                    options.open_browser
                    if getattr(options, "open_browser", None) is not None
                    else (
                        (os.environ.get("PA_CONTAINER_OPEN_BROWSER", "").strip().lower() in ("true", "1", "yes", "on"))
                        if "PA_CONTAINER_OPEN_BROWSER" in os.environ
                        else (
                            desktop_cfg.get("open_browser", False)
                            or getattr(global_config.runtime, "open_browser", False)
                        )
                    )
                )
                if eff_desktop_open_browser:
                    import webbrowser

                    def _open_desktop() -> None:
                        import time

                        time.sleep(1.5)
                        logger.info(f"Launching virtual desktop UI in default web browser: {desktop_novnc_url}")
                        webbrowser.open(desktop_novnc_url)

                    threading.Thread(target=_open_desktop, daemon=True).start()

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
