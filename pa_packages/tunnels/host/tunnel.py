from __future__ import annotations

import contextlib
import json
import re
import shutil
import subprocess
import sys
import time
import uuid
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

if TYPE_CHECKING:
    from contextlib import ExitStack

sys.dont_write_bytecode = True

from logging_driver import LogCategory, get_category_logger
from packages.plugin import IngressAuthPolicy, TunnelEndpoint, TunnelEndpointRequest, TunnelProvider
from secret_store import DEFAULT_KEYRING_SERVICE, get_keyring_secret

from .auth_gate import (
    OAuth2ProxyManager,
    TokenGateManager,
)

logger = get_category_logger(__name__, LogCategory.NETWORK)

FQDN_REGEX = re.compile(r"^(?=.{1,253}$)(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))*\.[A-Za-z]{2,}$")


class TunnelValidationError(Exception):
    """Raised when tunnel preflight checks or prerequisite validations fail."""


def format_error_box(title: str, lines: list[str]) -> str:
    """Format an eye-catching error box for terminal startup failures."""
    sep = "=" * 80
    body = "\n".join(f"  {line}" for line in lines)
    return f"\n{sep}\n  STARTUP ERROR: {title}\n{sep}\n{body}\n{sep}\n"


def validate_domain_fqdn(domain: str) -> bool:
    """Validate that a domain name is a syntactically valid FQDN."""
    if not domain or not isinstance(domain, str):
        return False
    clean = domain.strip().lower()
    if clean.startswith("http://") or clean.startswith("https://"):
        return False
    return bool(FQDN_REGEX.match(clean))


def resolve_tunnel_token(
    account: str = "CLOUDFLARE_TUNNEL_TOKEN",
    service: str = DEFAULT_KEYRING_SERVICE,
) -> str | None:
    """Resolve tunnel credentials exclusively from the OS keyring."""
    return get_keyring_secret(account=account, service=service)


def normalize_tunnel_url(raw_url: str) -> str:
    """Normalize any tunnel or public URL to strict HTTPS with no port.

    Examples:
      - 'http://t3.example.com:3773' -> 'https://t3.example.com'
      - 'https://t3.example.com:443/' -> 'https://t3.example.com'
      - 't3.example.com'             -> 'https://t3.example.com'
      - 'https://node.tailnet.ts.net' -> 'https://node.tailnet.ts.net'
    """
    if not raw_url or not isinstance(raw_url, str):
        raise TunnelValidationError("Tunnel URL must be a non-empty string.")

    clean = raw_url.strip()
    if not clean:
        raise TunnelValidationError("Tunnel URL must be a non-empty string.")

    if not clean.startswith(("http://", "https://")):
        if clean.count(":") > 1 and not clean.startswith("["):
            clean = f"[{clean}]"
        clean = f"https://{clean}"
    elif clean.startswith("http://"):
        rest = clean[7:]
        if rest.count(":") > 1 and not rest.startswith("["):
            rest = f"[{rest}]"
        clean = f"https://{rest}"

    parsed = urlparse(clean)
    hostname = parsed.hostname
    if not hostname:
        raise TunnelValidationError(f"Invalid tunnel URL: '{raw_url}'")

    hostname = hostname.lower()
    if ":" in hostname and not hostname.startswith("["):
        return f"https://[{hostname}]"
    return f"https://{hostname}"


def validate_tunnel_prerequisites(
    tunnel_type: str | None,
    domain: str | None = None,
    quick: bool = False,
    runner: str | None = None,
    keyring_account: str | None = None,
    tailscale_mode: str | None = None,
    runtime: str = "podman",
) -> None:
    """Validate generic tunnel prerequisites fail-fast on startup before initializing resources."""
    if not tunnel_type:
        if (quick or domain or keyring_account) and tailscale_mode:
            raise TunnelValidationError(
                format_error_box(
                    "Conflicting Tunnel Options",
                    [
                        "Both Cloudflare tunnel options and Tailscale tunnel options were specified.",
                        "Please choose either Cloudflare or Tailscale.",
                    ],
                )
            )
        return

    ttype = tunnel_type.strip().lower()
    if ttype not in ("tailscale", "cloudflare"):
        raise TunnelValidationError(
            format_error_box(
                f"Unsupported Tunnel Type '{tunnel_type}'",
                [
                    f"The specified tunnel type '{tunnel_type}' is not supported.",
                    "Supported tunnel options:",
                    "  --tunnel tailscale   (Private WireGuard mesh with automated HTTPS)",
                    "  --tunnel cloudflare  (Cloudflare Zero Trust tunnel)",
                ],
            )
        )

    if ttype == "tailscale":
        if quick or domain or keyring_account:
            raise TunnelValidationError(
                format_error_box(
                    "Conflicting Tunnel Options",
                    [
                        "Options --tunnel-quick, --tunnel-domain, and --tunnel-keyring-account",
                        "are Cloudflare-specific and cannot be used with Tailscale tunnels.",
                    ],
                )
            )
        _validate_tailscale_prerequisites()
    elif ttype == "cloudflare":
        if tailscale_mode:
            raise TunnelValidationError(
                format_error_box(
                    "Conflicting Tunnel Options",
                    [
                        "Option --tunnel-tailscale-mode is Tailscale-specific and cannot be used with Cloudflare tunnels.",
                    ],
                )
            )
        _validate_cloudflare_prerequisites(
            domain=domain,
            quick=quick,
            runner=runner or "auto",
            keyring_account=keyring_account or "CLOUDFLARE_TUNNEL_TOKEN",
            runtime=runtime,
        )


def _validate_tailscale_prerequisites() -> None:
    """Validate host Tailscale installation and daemon state."""
    tailscale_bin = shutil.which("tailscale")
    if not tailscale_bin:
        raise TunnelValidationError(
            format_error_box(
                "Tailscale is not installed on the host",
                [
                    "You configured '--tunnel tailscale', but the 'tailscale' binary",
                    "was not found on your host PATH.",
                    "",
                    "Required Actions:",
                    "  1. Install Tailscale on your host machine:",
                    "     - macOS: brew install tailscale (or install the Tailscale App)",
                    "     - Linux: curl -fsSL https://tailscale.com/install.sh | sh",
                    "  2. Authenticate and connect:",
                    "     - Run: tailscale up",
                    "  3. Re-run pa:",
                    "     - pa run --tunnel tailscale",
                ],
            )
        )

    try:
        res = subprocess.run(
            [tailscale_bin, "status", "--json"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        if res.returncode != 0:
            raise RuntimeError(res.stderr or "daemon unreachable")
        status_data = json.loads(res.stdout) if res.stdout else {}
        backend_state = status_data.get("BackendState", "")
        if backend_state not in ("Running", "Starting"):
            raise TunnelValidationError(
                format_error_box(
                    "Tailscale daemon is not authenticated or running",
                    [
                        f"Tailscale is installed, but reports state '{backend_state}'.",
                        "",
                        "Required Actions:",
                        "  1. Connect this device to your Tailnet:",
                        "     - Run: tailscale up",
                        "  2. Verify connection:",
                        "     - Run: tailscale status",
                        "  3. Re-run pa.",
                    ],
                )
            )
    except TunnelValidationError:
        raise
    except Exception as e:
        raise TunnelValidationError(
            format_error_box(
                "Unable to communicate with Tailscale daemon",
                [
                    f"Tailscale daemon status check failed: {e}",
                    "",
                    "Ensure the Tailscale service is running on the host:",
                    "  - Run: tailscale up",
                ],
            )
        ) from e


def _validate_cloudflare_prerequisites(
    domain: str | None,
    quick: bool,
    runner: str,
    keyring_account: str,
    runtime: str,
) -> None:
    """Validate Cloudflare tunnel arguments, domain, keyring credentials, and runners."""
    if not quick:
        if not domain:
            raise TunnelValidationError(
                format_error_box(
                    "Cloudflare Tunnel Domain Missing",
                    [
                        "You configured '--tunnel cloudflare', but did not specify your user-owned",
                        "domain on Cloudflare.",
                        "",
                        "Required Actions:",
                        "  1. Specify your user-owned domain via --tunnel-domain:",
                        "     - pa run --tunnel cloudflare --tunnel-domain yourdomain.com",
                        "",
                        "  2. (Alternatively) Run a zero-setup ephemeral tunnel without a custom domain:",
                        "     - pa run --tunnel cloudflare --tunnel-quick",
                    ],
                )
            )
        if not validate_domain_fqdn(domain):
            raise TunnelValidationError(
                format_error_box(
                    "Invalid Domain Name",
                    [
                        f"The value '{domain}' supplied to --tunnel-domain is not a valid",
                        "fully-qualified domain name (FQDN).",
                        "",
                        "Expected format:",
                        "  yourdomain.com or subdomain.yourdomain.com",
                    ],
                )
            )

        token = resolve_tunnel_token(account=keyring_account)
        if not token:
            raise TunnelValidationError(
                format_error_box(
                    "Cloudflare Tunnel Token not found in OS Keyring",
                    [
                        f"You requested a named Cloudflare tunnel for '{domain}', but no",
                        f"tunnel token was found in the OS keyring under service '{DEFAULT_KEYRING_SERVICE}'",
                        f"and account '{keyring_account}'.",
                        "",
                        "Required Actions:",
                        "  1. Retrieve your tunnel token from the Cloudflare Zero Trust dashboard:",
                        "     (Networks -> Tunnels -> Select Tunnel -> Copy token)",
                        "  2. Save it securely in your OS keyring:",
                        f"     - Run: uv run keyring set {DEFAULT_KEYRING_SERVICE} {keyring_account}",
                        "  3. Re-run pa.",
                    ],
                )
            )

    runner_mode = runner.strip().lower()
    if runner_mode not in ("auto", "host", "container"):
        raise TunnelValidationError(
            format_error_box(
                f"Invalid Tunnel Runner '{runner}'",
                [
                    f"Runner '{runner}' is invalid. Expected: 'auto', 'host', or 'container'.",
                ],
            )
        )

    has_host_bin = bool(shutil.which("cloudflared"))
    has_runtime = bool(shutil.which(runtime))

    if runner_mode == "host" and not has_host_bin:
        raise TunnelValidationError(
            format_error_box(
                "Host binary 'cloudflared' not found",
                [
                    "You configured '--tunnel-runner host', but 'cloudflared' was not found on your host PATH.",
                    "",
                    "Required Actions:",
                    "  - Install cloudflared: brew install cloudflared (macOS) or apt/dnf install cloudflared",
                    "  - Or use containerized mode: --tunnel-runner container (or --tunnel-runner auto)",
                ],
            )
        )

    if runner_mode == "container" and not has_runtime:
        raise TunnelValidationError(
            format_error_box(
                f"Container runtime '{runtime}' not found",
                [
                    f"You configured '--tunnel-runner container', but '{runtime}' was not found on your host PATH.",
                ],
            )
        )

    if runner_mode == "auto" and not has_host_bin and not has_runtime:
        raise TunnelValidationError(
            format_error_box(
                "Unable to run cloudflared (binary and container runtime unavailable)",
                [
                    "'cloudflared' was not found on your host PATH, and running containerized",
                    f"via '{runtime}' is not available.",
                    "",
                    "Required Actions:",
                    "  - Install cloudflared: brew install cloudflared (macOS)",
                    f"  - OR ensure container runtime '{runtime}' is installed and in PATH.",
                ],
            )
        )


class TailscaleTunnelManager:
    """Manages Tailscale tunnel integration and MagicDNS HTTPS exposure."""

    def __init__(self, mode: str | None = None) -> None:
        self.mode = (mode or "serve").strip().lower()
        self.tailscale_bin = shutil.which("tailscale") or "tailscale"
        self._fqdn: str | None = None
        self._ipv4: str | None = None
        self._query_status()

    def start_endpoint(self, port: int, stack: ExitStack, service_name: str = "service") -> tuple[str, str]:
        """Start or configure Tailscale Serve for a given port."""
        advertised_host = self._fqdn or self._ipv4 or "localhost"

        if self.mode == "serve":
            logger.info(f"Enabling Tailscale Serve on host port {port} ({service_name}) with MagicDNS HTTPS...")
            try:
                subprocess.run(
                    [self.tailscale_bin, "serve", "--bg", str(port)],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
            except Exception as e:
                logger.warning(f"Tailscale Serve execution warning: {e}")

            def _cleanup() -> None:
                logger.info(f"Cleaning up Tailscale Serve for port {port}...")
                with contextlib.suppress(Exception):
                    subprocess.run(
                        [self.tailscale_bin, "serve", "reset"],
                        check=False,
                        capture_output=True,
                        timeout=5,
                    )

            stack.callback(_cleanup)
            raw_url = f"https://{advertised_host}"
        else:
            raw_url = f"https://{self._ipv4 or advertised_host}"

        public_url = normalize_tunnel_url(raw_url)
        return public_url, advertised_host

    def _query_status(self) -> None:
        try:
            res = subprocess.run(
                [self.tailscale_bin, "status", "--json"],
                capture_output=True,
                text=True,
                check=True,
                timeout=5,
            )
            data = json.loads(res.stdout)
            self_node = data.get("Self", {})
            dns_name = self_node.get("DNSName", "").rstrip(".")
            ips = self_node.get("TailscaleIPs", [])
            ipv4 = next((ip for ip in ips if ":" not in ip), None)
            self._fqdn = dns_name or None
            self._ipv4 = ipv4
        except Exception as e:
            logger.debug(f"Tailscale status query: {e}")


class CloudflareTunnelManager:
    """Manages Cloudflare Tunnel execution (host binary or containerized sidecar)."""

    def __init__(
        self,
        domain: str | None = None,
        quick: bool = False,
        runner: str | None = None,
        keyring_account: str | None = None,
        runtime: str = "podman",
        run_id: str | None = None,
    ) -> None:
        self.domain = domain.strip().lower() if domain else None
        self.quick = quick
        self.runner = (runner or "auto").strip().lower()
        self.keyring_account = keyring_account or "CLOUDFLARE_TUNNEL_TOKEN"
        self.runtime = runtime
        self.run_id = run_id or uuid.uuid4().hex[:8]

    def start_endpoint(
        self,
        port: int,
        stack: ExitStack,
        service_name: str = "service",
        preferred_subdomain: str | None = None,
    ) -> tuple[str, str]:
        """Start Cloudflare tunnel process for a given endpoint and register teardown."""
        use_host = self.runner == "host" or (self.runner == "auto" and bool(shutil.which("cloudflared")))

        if self.quick:
            return self._start_quick_tunnel(port=port, use_host=use_host, stack=stack, service_name=service_name)
        return self._start_named_tunnel(
            port=port,
            use_host=use_host,
            stack=stack,
            service_name=service_name,
            preferred_subdomain=preferred_subdomain,
        )

    def _start_named_tunnel(
        self,
        port: int,
        use_host: bool,
        stack: ExitStack,
        service_name: str,
        preferred_subdomain: str | None = None,
    ) -> tuple[str, str]:
        token = resolve_tunnel_token(account=self.keyring_account)
        if not token:
            raise TunnelValidationError(f"Tunnel token '{self.keyring_account}' not found in keyring.")

        container_name = f"pa-container-tunnel-cf-{service_name}-{self.run_id}"

        if use_host:
            cmd = ["cloudflared", "tunnel", "run", "--token", token]
            logger.info(f"Starting host cloudflared tunnel for {service_name} on domain {self.domain}...")
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            stack.callback(lambda: self._terminate_proc(proc))
        else:
            cmd = [
                self.runtime,
                "run",
                "--rm",
                "--name",
                container_name,
                "--network",
                "host",
                "docker.io/cloudflare/cloudflared:latest",
                "tunnel",
                "run",
                "--token",
                token,
            ]
            logger.info(
                f"Starting containerized cloudflared tunnel ({self.runtime}) for {service_name} on domain {self.domain}..."
            )
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            stack.callback(lambda: self._cleanup_container(proc, container_name))

        sub = preferred_subdomain or service_name
        target_host = (
            f"{sub}.{self.domain}"
            if self.domain and not self.domain.startswith(f"{sub}.")
            else (self.domain or "localhost")
        )
        public_url = normalize_tunnel_url(target_host)
        return public_url, target_host

    def _start_quick_tunnel(
        self,
        port: int,
        use_host: bool,
        stack: ExitStack,
        service_name: str,
    ) -> tuple[str, str]:
        local_target = f"http://127.0.0.1:{port}"
        container_name = f"pa-container-tunnel-cf-{service_name}-{self.run_id}"

        if use_host:
            cmd = ["cloudflared", "tunnel", "--url", local_target]
            logger.info(f"Starting host cloudflared quick tunnel for {service_name} (port {port})...")
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            stack.callback(lambda: self._terminate_proc(proc))
        else:
            cmd = [
                self.runtime,
                "run",
                "--rm",
                "--name",
                container_name,
                "--network",
                "host",
                "docker.io/cloudflare/cloudflared:latest",
                "tunnel",
                "--url",
                local_target,
            ]
            logger.info(
                f"Starting containerized cloudflared quick tunnel ({self.runtime}) for {service_name} (port {port})..."
            )
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            stack.callback(lambda: self._cleanup_container(proc, container_name))

        quick_url: str | None = None
        start_time = time.time()
        timeout = 30.0

        if proc and proc.stderr:
            while time.time() - start_time < timeout:
                line = proc.stderr.readline()
                if not line and proc.poll() is not None:
                    break
                match = re.search(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", line)
                if match:
                    quick_url = match.group(0)
                    break

        if not quick_url:
            logger.warning(
                f"Could not automatically parse trycloudflare.com URL for {service_name} from cloudflared logs."
            )
            quick_url = f"https://{service_name}-quick-tunnel.trycloudflare.com"

        public_url = normalize_tunnel_url(quick_url)
        advertised_host = urlparse(public_url).hostname or "localhost"
        return public_url, advertised_host

    def _terminate_proc(self, proc: subprocess.Popen[str] | subprocess.Popen[bytes] | None) -> None:
        if proc and proc.poll() is None:
            logger.info("Stopping cloudflared process...")
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except Exception as e:
                logger.debug(f"Cloudflared terminate wait timed out, killing: {e}")
                proc.kill()

    def _cleanup_container(self, proc: subprocess.Popen[str] | subprocess.Popen[bytes] | None, name: str) -> None:
        self._terminate_proc(proc)
        with contextlib.suppress(Exception):
            subprocess.run(
                [self.runtime, "rm", "-f", name],
                capture_output=True,
                check=False,
                timeout=5,
            )


class TunnelService(TunnelProvider):
    """Orchestrates generic multi-service tunneling and access control gating."""

    def __init__(
        self,
        provider: str | None = None,
        domain: str | None = None,
        quick: bool = False,
        runner: str = "auto",
        keyring_account: str = "CLOUDFLARE_TUNNEL_TOKEN",
        tailscale_mode: str = "serve",
        auth_mode: str = "auto",
        oidc_config: dict[str, Any] | None = None,
        basic_creds: tuple[str, str] | None = None,
        selected_services: list[str] | None = None,
        runtime: str = "podman",
        allow_insecure: bool = False,
    ) -> None:
        self.provider = provider.strip().lower() if provider else None
        self.domain = domain
        self.quick = quick
        self.runner = runner
        self.keyring_account = keyring_account
        self.tailscale_mode = tailscale_mode
        self.auth_mode = auth_mode
        self.oidc_config = oidc_config
        self.basic_creds = basic_creds
        self.selected_services = selected_services
        self.runtime = runtime
        self.allow_insecure = allow_insecure

        self.requests: dict[str, TunnelEndpointRequest] = {}
        self.endpoints: dict[str, TunnelEndpoint] = {}
        self.exit_stack: ExitStack | None = None

        self._ts_mgr: TailscaleTunnelManager | None = None
        self._cf_mgr: CloudflareTunnelManager | None = None

    def is_enabled(self) -> bool:
        """Whether a tunnel provider is actively enabled."""
        return bool(self.provider)

    def register_service(self, request: TunnelEndpointRequest) -> TunnelEndpoint | None:
        """Register a service endpoint request and provision immediately if exit stack is active."""
        self.requests[request.service_name] = request
        if self.exit_stack is not None and self.is_enabled():
            return self._provision_single(request, self.exit_stack)
        return self.endpoints.get(request.service_name)

    def get_endpoint(self, service_name: str) -> TunnelEndpoint | None:
        """Retrieve active provisioned tunnel endpoint for a service."""
        return self.endpoints.get(service_name)

    def provision_all(self, exit_stack: ExitStack) -> dict[str, TunnelEndpoint]:
        """Provision all registered endpoints that have not yet been started."""
        self.exit_stack = exit_stack
        if not self.is_enabled():
            return self.endpoints

        for req in self.requests.values():
            if req.service_name not in self.endpoints:
                self._provision_single(req, exit_stack)

        return self.endpoints

    def _provision_single(self, request: TunnelEndpointRequest, stack: ExitStack) -> TunnelEndpoint | None:
        if self.selected_services and request.service_name not in self.selected_services:
            logger.debug(f"Service '{request.service_name}' skipped by tunnel service filter.")
            return None

        origin_port = request.port
        is_gated = False
        active_auth_mode = "none"
        access_token: str | None = None

        # Determine if access control gating is required
        needs_gate = request.auth_policy == IngressAuthPolicy.REQUIRED and not self.allow_insecure
        # Tailscale Serve operates on the private tailnet perimeter
        if (
            self.provider == "tailscale"
            and self.tailscale_mode == "serve"
            and not self.oidc_config
            and not self.basic_creds
        ):
            needs_gate = False

        if needs_gate:
            is_gated = True
            if self.auth_mode == "oidc" and self.oidc_config:
                active_auth_mode = "oidc"
                oidc_mgr = OAuth2ProxyManager(
                    upstream_port=request.port,
                    oidc_config=self.oidc_config,
                    runtime=self.runtime,
                    title=request.title or request.service_name,
                )
                origin_port = oidc_mgr.start(stack)
            elif self.auth_mode == "basic" and self.basic_creds:
                active_auth_mode = "basic"
                gate_mgr = TokenGateManager(
                    upstream_port=request.port,
                    basic_creds=self.basic_creds,
                    title=request.title or request.service_name,
                )
                origin_port = gate_mgr.start(stack)
            else:
                # Default token gate
                active_auth_mode = "token"
                gate_mgr = TokenGateManager(
                    upstream_port=request.port,
                    basic_creds=self.basic_creds,
                    title=request.title or request.service_name,
                )
                origin_port = gate_mgr.start(stack)
                access_token = gate_mgr.token
        elif request.auth_policy == IngressAuthPolicy.INTRINSIC:
            active_auth_mode = "intrinsic"

        # Provision tunnel for origin_port
        if self.provider == "tailscale":
            if not self._ts_mgr:
                self._ts_mgr = TailscaleTunnelManager(mode=self.tailscale_mode)
            pub_url, adv_host = self._ts_mgr.start_endpoint(
                port=origin_port,
                stack=stack,
                service_name=request.service_name,
            )
        elif self.provider == "cloudflare":
            if not self._cf_mgr:
                self._cf_mgr = CloudflareTunnelManager(
                    domain=self.domain,
                    quick=self.quick,
                    runner=self.runner,
                    keyring_account=self.keyring_account,
                    runtime=self.runtime,
                )
            pub_url, adv_host = self._cf_mgr.start_endpoint(
                port=origin_port,
                stack=stack,
                service_name=request.service_name,
                preferred_subdomain=request.preferred_subdomain,
            )
        else:
            pub_url = f"http://127.0.0.1:{origin_port}"
            adv_host = "localhost"

        endpoint = TunnelEndpoint(
            request=request,
            public_url=pub_url,
            advertised_host=adv_host,
            is_gated=is_gated,
            auth_mode=active_auth_mode,
            access_token=access_token,
        )
        self.endpoints[request.service_name] = endpoint
        return endpoint
