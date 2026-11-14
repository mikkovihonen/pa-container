from __future__ import annotations

import base64
import contextlib
import hashlib
import hmac
import re
import secrets
import select
import shutil
import socket
import subprocess
import sys
import threading
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlparse

if TYPE_CHECKING:
    from contextlib import ExitStack

sys.dont_write_bytecode = True

from logging_driver import LogCategory, get_category_logger
from secret_store import DEFAULT_KEYRING_SERVICE, get_keyring_secret

logger = get_category_logger(__name__, LogCategory.NETWORK)


class AuthGateValidationError(Exception):
    """Raised when authentication gate configuration or credential resolution fails."""


def format_auth_error_box(title: str, lines: list[str]) -> str:
    """Format an eye-catching error box for authentication gate preflight failures."""
    sep = "=" * 80
    body = "\n".join(f"  {line}" for line in lines)
    return f"\n{sep}\n  AUTHENTICATION ERROR: {title}\n{sep}\n{body}\n{sep}\n"


def validate_basic_auth_credentials(
    username: str | None,
    keyring_account: str | None,
    service: str = DEFAULT_KEYRING_SERVICE,
) -> tuple[str, str]:
    """Validate and resolve HTTP Basic Auth credentials with strict explicit sourcing.

    Automatic fallbacks to default passwords or implicit keyring accounts are forbidden.
    """
    clean_user = (username or "").strip()
    clean_account = (keyring_account or "").strip()

    if not clean_user or not clean_account:
        missing = []
        if not clean_user:
            missing.append("Username (--tunnel-basic-user or tunnels.config.auth.basic.username)")
        if not clean_account:
            missing.append(
                "Keyring account (--tunnel-basic-keyring-account or tunnels.config.auth.basic.password_keyring_account)"
            )
        raise AuthGateValidationError(
            format_auth_error_box(
                "Incomplete Basic Auth Configuration",
                [
                    "HTTP Basic Auth username and password source must be explicitly configured.",
                    "Automatic credential fallbacks are disabled for security.",
                    "",
                    "Missing parameters:",
                    *[f"  - {m}" for m in missing],
                    "",
                    "Required Actions:",
                    "  1. Pass --tunnel-basic-user <user> and --tunnel-basic-keyring-account <account>",
                    "     OR configure packages: tunnels: config: auth: basic: in config.yaml.",
                    f"  2. Ensure the password is stored in OS keyring: uv run keyring set {service} <account>",
                ],
            )
        )

    password = get_keyring_secret(account=clean_account, service=service)
    if not password:
        raise AuthGateValidationError(
            format_auth_error_box(
                "Basic Auth Password Not Found in OS Keyring",
                [
                    f"Basic Auth was configured for user '{clean_user}', but no password was found",
                    f"in OS keyring service '{service}' under account '{clean_account}'.",
                    "",
                    "Required Action:",
                    f"  Set the password in your OS keyring: uv run keyring set {service} {clean_account}",
                ],
            )
        )

    return clean_user, password


def validate_oidc_config(
    provider: str | None,
    client_id: str | None,
    client_secret_account: str | None,
    issuer_url: str | None = None,
    email_domains: list[str] | None = None,
    service: str = DEFAULT_KEYRING_SERVICE,
) -> dict[str, Any]:
    """Validate OIDC / OAuth2 configuration parameters and resolve client secret from keyring."""
    clean_provider = (provider or "google").strip().lower()
    clean_client_id = (client_id or "").strip()
    clean_secret_acct = (client_secret_account or "").strip()

    if not clean_client_id or not clean_secret_acct:
        missing = []
        if not clean_client_id:
            missing.append("Client ID (tunnels.config.auth.oidc.client_id)")
        if not clean_secret_acct:
            missing.append("Client Secret Keyring Account (tunnels.config.auth.oidc.client_secret_keyring_account)")
        raise AuthGateValidationError(
            format_auth_error_box(
                "Incomplete OIDC Configuration",
                [
                    f"OIDC authentication for provider '{clean_provider}' requires client credentials.",
                    "",
                    "Missing parameters:",
                    *[f"  - {m}" for m in missing],
                    "",
                    "Required Actions:",
                    "  1. Configure client_id and client_secret_keyring_account in config.yaml.",
                    f"  2. Store client secret in keyring: uv run keyring set {service} <account>",
                ],
            )
        )

    client_secret = get_keyring_secret(account=clean_secret_acct, service=service)
    if not client_secret:
        raise AuthGateValidationError(
            format_auth_error_box(
                "OIDC Client Secret Not Found in OS Keyring",
                [
                    f"OIDC provider '{clean_provider}' configured account '{clean_secret_acct}', but no",
                    f"secret was found in OS keyring service '{service}'.",
                    "",
                    "Required Action:",
                    f"  Set client secret in your OS keyring: uv run keyring set {service} {clean_secret_acct}",
                ],
            )
        )

    return {
        "provider": clean_provider,
        "client_id": clean_client_id,
        "client_secret": client_secret,
        "issuer_url": issuer_url,
        "email_domains": email_domains or ["*"],
    }


def find_available_port(start_port: int = 16080, max_attempts: int = 100) -> int:
    """Find an available local TCP port on 127.0.0.1."""
    for p in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    # Fallback to system-allocated ephemeral port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class TokenGateManager:
    """Zero-dependency local session token & basic auth gate.

    Intercepts HTTP requests, validates session cookies, magic tokens, or explicit
    HTTP Basic Auth, and proxies HTTP and duplex WebSocket streams to upstream.
    """

    def __init__(
        self,
        upstream_port: int,
        listen_port: int | None = None,
        basic_creds: tuple[str, str] | None = None,
        title: str = "Protected Service",
    ) -> None:
        self.upstream_port = upstream_port
        self.listen_port = listen_port or find_available_port(start_port=16080)
        self.basic_creds = basic_creds
        self.title = title
        self.token = secrets.token_urlsafe(24)
        self.hmac_secret = secrets.token_bytes(32)
        self._server_sock: socket.socket | None = None
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self, stack: ExitStack) -> int:
        """Start the token gate listener thread and register teardown."""
        self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_sock.bind(("127.0.0.1", self.listen_port))
        self._server_sock.listen(128)
        self._server_sock.settimeout(1.0)

        self._thread = threading.Thread(target=self._run_accept_loop, daemon=True)
        self._thread.start()

        def _cleanup() -> None:
            self._stop_event.set()
            if self._server_sock:
                with contextlib.suppress(Exception):
                    self._server_sock.close()
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=1.0)

        stack.callback(_cleanup)
        logger.info(
            f"Ingress Auth Gate active for {self.title} on 127.0.0.1:{self.listen_port} -> 127.0.0.1:{self.upstream_port}"
        )
        return self.listen_port

    def _sign_cookie(self, payload: str) -> str:
        sig = hmac.new(self.hmac_secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()
        return f"{payload}.{sig}"

    def _verify_cookie(self, cookie_val: str | None) -> bool:
        if not cookie_val or "." not in cookie_val:
            return False
        payload, sig = cookie_val.rsplit(".", 1)
        expected = hmac.new(self.hmac_secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, expected)

    def _run_accept_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                if not self._server_sock:
                    break
                client_sock, _ = self._server_sock.accept()
                threading.Thread(target=self._handle_client, args=(client_sock,), daemon=True).start()
            except TimeoutError:
                continue
            except OSError:
                break
            except Exception as e:
                logger.debug(f"Auth gate accept exception: {e}")

    def _handle_client(self, client: socket.socket) -> None:
        try:
            client.settimeout(10.0)
            initial_data = b""
            while b"\r\n\r\n" not in initial_data and len(initial_data) < 65536:
                chunk = client.recv(4096)
                if not chunk:
                    break
                initial_data += chunk

            if not initial_data:
                client.close()
                return

            header_part, _, body_rest = initial_data.partition(b"\r\n\r\n")
            header_str = header_part.decode("utf-8", errors="replace")
            lines = header_str.split("\r\n")
            if not lines:
                client.close()
                return

            req_line = lines[0]
            parts = req_line.split(" ")
            if len(parts) < 2:
                client.close()
                return

            _method, target = parts[0], parts[1]
            parsed = urlparse(target)
            query = parse_qs(parsed.query)

            # Check magic link query param: ?pa_token=...
            magic_token = query.get("pa_token", [None])[0]
            if magic_token and hmac.compare_digest(magic_token, self.token):
                # Valid token in URL -> issue session cookie and redirect to clean URL
                signed = self._sign_cookie("session_auth")
                clean_path = parsed.path or "/"
                # Preserve remaining query params except pa_token
                rem_query = "&".join(f"{k}={v[0]}" for k, v in query.items() if k != "pa_token")
                dest = f"{clean_path}?{rem_query}" if rem_query else clean_path
                resp = (
                    f"HTTP/1.1 302 Found\r\n"
                    f"Location: {dest}\r\n"
                    f"Set-Cookie: pa_session={signed}; Path=/; HttpOnly; SameSite=Lax\r\n"
                    f"Content-Length: 0\r\n\r\n"
                )
                client.sendall(resp.encode("utf-8"))
                client.close()
                return

            # Check Cookie header
            is_authed = False
            cookie_match = re.search(r"pa_session=([^;\s]+)", header_str)
            if cookie_match and self._verify_cookie(cookie_match.group(1)):
                is_authed = True

            # Check HTTP Basic Auth header if configured
            if not is_authed and self.basic_creds:
                auth_match = re.search(r"Authorization:\s*Basic\s+([A-Za-z0-9+/=]+)", header_str, re.IGNORECASE)
                if auth_match:
                    try:
                        decoded = base64.b64decode(auth_match.group(1)).decode("utf-8")
                        u, _, p = decoded.partition(":")
                        exp_u, exp_p = self.basic_creds
                        if hmac.compare_digest(u, exp_u) and hmac.compare_digest(p, exp_p):
                            is_authed = True
                    except Exception:
                        pass

            if not is_authed:
                # Unauthorized -> send 401 response with login/token prompt
                body = (
                    "<!DOCTYPE html><html><head><meta charset='utf-8'>"
                    f"<title>{self.title} - Authentication Required</title>"
                    "<style>body{font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;background:#0f172a;color:#f8fafc;}"
                    ".card{background:#1e293b;padding:2rem;border-radius:0.75rem;box-shadow:0 10px 25px rgba(0,0,0,0.5);width:360px;}"
                    "h2{margin-top:0;font-size:1.25rem;color:#38bdf8;}input{width:100%;box-sizing:border-box;padding:0.75rem;margin:1rem 0;border-radius:0.375rem;border:1px solid #475569;background:#0f172a;color:#fff;}"
                    "button{width:100%;padding:0.75rem;background:#0284c7;border:none;border-radius:0.375rem;color:#fff;font-weight:bold;cursor:pointer;}"
                    "button:hover{background:#0369a1;}</style></head><body>"
                    f"<div class='card'><h2>{self.title}</h2><p style='font-size:0.875rem;color:#94a3b8;'>Access to this container service is restricted. Enter your session token or use the magic link provided on launch.</p>"
                    "<form method='GET'><input type='password' name='pa_token' placeholder='Session Token' required autofocus><button type='submit'>Authenticate</button></form>"
                    "</div></body></html>"
                )
                resp = (
                    f"HTTP/1.1 401 Unauthorized\r\n"
                    f"Content-Type: text/html; charset=utf-8\r\n"
                    f"Content-Length: {len(body.encode('utf-8'))}\r\n"
                    f'WWW-Authenticate: Basic realm="{self.title}"\r\n\r\n'
                    f"{body}"
                )
                client.sendall(resp.encode("utf-8"))
                client.close()
                return

            # Authenticated! Forward request to upstream backend
            backend = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            backend.connect(("127.0.0.1", self.upstream_port))
            backend.sendall(initial_data)

            # Bidirectional stream proxy (handles both standard HTTP and WebSocket duplex)
            self._splice_sockets(client, backend)
        except Exception as e:
            logger.debug(f"Auth gate client handling error: {e}")
            with contextlib.suppress(Exception):
                client.close()

    def _splice_sockets(self, s1: socket.socket, s2: socket.socket) -> None:
        """Bidirectionally splice two TCP sockets."""
        s1.setblocking(False)
        s2.setblocking(False)
        sockets = [s1, s2]
        while not self._stop_event.is_set():
            try:
                r, _, w = select.select(sockets, [], sockets, 30.0)
                if w:
                    break
                if not r:
                    continue
                for sock in r:
                    peer = s2 if sock is s1 else s1
                    data = sock.recv(32768)
                    if not data:
                        return
                    peer.sendall(data)
            except OSError:
                break
        with contextlib.suppress(Exception):
            s1.close()
        with contextlib.suppress(Exception):
            s2.close()


class OAuth2ProxyManager:
    """Manages containerized oauth2-proxy sidecar for corporate OIDC / OAuth SSO."""

    def __init__(
        self,
        upstream_port: int,
        oidc_config: dict[str, Any],
        listen_port: int | None = None,
        runtime: str = "podman",
        run_id: str | None = None,
        title: str = "Protected Service",
    ) -> None:
        self.upstream_port = upstream_port
        self.listen_port = listen_port or find_available_port(start_port=16080)
        self.oidc_config = oidc_config
        self.runtime = runtime
        self.run_id = run_id or "default"
        self.title = title
        self._container_name = f"pa-container-auth-gate-{self.run_id}"
        self._proc: subprocess.Popen[str] | subprocess.Popen[bytes] | None = None

    def start(self, stack: ExitStack) -> int:
        """Launch the oauth2-proxy sidecar container and register cleanup."""
        has_runtime = bool(shutil.which(self.runtime))
        if not has_runtime:
            raise AuthGateValidationError(
                format_auth_error_box(
                    f"Container Runtime '{self.runtime}' Not Found",
                    [
                        f"Running the OIDC auth gate requires '{self.runtime}' to be installed on host PATH.",
                    ],
                )
            )

        cookie_secret = base64.b64encode(secrets.token_bytes(32)).decode("ascii")
        cmd = [
            self.runtime,
            "run",
            "--rm",
            "--name",
            self._container_name,
            "--network",
            "host",
            "quay.io/oauth2-proxy/oauth2-proxy:latest",
            f"--http-address=http://127.0.0.1:{self.listen_port}",
            f"--upstream=http://127.0.0.1:{self.upstream_port}",
            f"--provider={self.oidc_config['provider']}",
            f"--client-id={self.oidc_config['client_id']}",
            f"--client-secret={self.oidc_config['client_secret']}",
            f"--cookie-secret={cookie_secret}",
            "--proxy-websockets=true",
            "--cookie-secure=false",  # Local port; SSL terminates at tunnel ingress
            "--silence-ping-logging=true",
        ]

        if self.oidc_config.get("issuer_url"):
            cmd.append(f"--oidc-issuer-url={self.oidc_config['issuer_url']}")

        for domain in self.oidc_config.get("email_domains", []):
            cmd.append(f"--email-domain={domain}")

        logger.info(
            f"Starting OAuth2 Proxy OIDC sidecar ({self.oidc_config['provider']}) on 127.0.0.1:{self.listen_port} -> 127.0.0.1:{self.upstream_port}..."
        )
        self._proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        def _cleanup() -> None:
            logger.info("Cleaning up OAuth2 Proxy container...")
            if self._proc and self._proc.poll() is None:
                self._proc.terminate()
            with contextlib.suppress(Exception):
                subprocess.run(
                    [self.runtime, "rm", "-f", self._container_name],
                    capture_output=True,
                    check=False,
                    timeout=5,
                )

        stack.callback(_cleanup)
        return self.listen_port
