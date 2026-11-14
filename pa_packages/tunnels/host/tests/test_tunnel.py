from __future__ import annotations

import contextlib
from contextlib import ExitStack
from typing import TYPE_CHECKING
from unittest.mock import patch
from urllib.parse import urlparse

if TYPE_CHECKING:
    from pathlib import Path

import pytest
from pa_packages.tunnels.host.auth_gate import (
    AuthGateValidationError,
    TokenGateManager,
    validate_basic_auth_credentials,
    validate_oidc_config,
)
from pa_packages.tunnels.host.plugin import TunnelsPlugin
from pa_packages.tunnels.host.tunnel import (
    TunnelService,
    TunnelValidationError,
    format_error_box,
    normalize_tunnel_url,
    validate_domain_fqdn,
    validate_tunnel_prerequisites,
)

from packages.plugin import IngressAuthPolicy, RunContext, TunnelEndpointRequest


def test_tunnel_url_normalization() -> None:
    raw_url = "http://app.example.com:3773"
    public_url = normalize_tunnel_url(raw_url)
    assert public_url == "https://app.example.com"
    assert ":3773" not in public_url
    assert urlparse(public_url).hostname == "app.example.com"


def test_tunnel_url_normalization_bare_domain() -> None:
    raw_url = "app.example.com"
    public_url = normalize_tunnel_url(raw_url)
    assert public_url == "https://app.example.com"


def test_tunnel_url_normalization_invalid() -> None:
    with pytest.raises(TunnelValidationError):
        normalize_tunnel_url("")

    with pytest.raises(TunnelValidationError):
        normalize_tunnel_url("   ")


def test_validate_domain_fqdn() -> None:
    assert validate_domain_fqdn("sub.domain.example.com") is True
    assert validate_domain_fqdn("example.com") is True
    assert validate_domain_fqdn("https://example.com") is False
    assert validate_domain_fqdn("invalid domain") is False
    assert validate_domain_fqdn("") is False


def test_format_error_box() -> None:
    box = format_error_box("Test Failure", ["Line 1", "Line 2"])
    assert "STARTUP ERROR: Test Failure" in box
    assert "Line 1" in box
    assert "Line 2" in box


def test_validate_tunnel_prerequisites_conflicts() -> None:
    # Conflicting provider options
    with pytest.raises(TunnelValidationError, match="Conflicting Tunnel Options"):
        validate_tunnel_prerequisites(
            tunnel_type="tailscale",
            quick=True,
        )

    with pytest.raises(TunnelValidationError, match="Conflicting Tunnel Options"):
        validate_tunnel_prerequisites(
            tunnel_type="cloudflare",
            tailscale_mode="serve",
        )

    with pytest.raises(TunnelValidationError, match="Unsupported Tunnel Type"):
        validate_tunnel_prerequisites(tunnel_type="invalid_provider")


def test_validate_cloudflare_prerequisites() -> None:
    with patch("shutil.which", return_value="/usr/local/bin/podman"):
        # Missing domain for non-quick
        with pytest.raises(TunnelValidationError, match="Cloudflare Tunnel Domain Missing"):
            validate_tunnel_prerequisites(tunnel_type="cloudflare", quick=False)

        # Invalid domain
        with pytest.raises(TunnelValidationError, match="Invalid Domain Name"):
            validate_tunnel_prerequisites(tunnel_type="cloudflare", domain="not a domain", quick=False)

        # Missing token in keyring
        with (
            patch("pa_packages.tunnels.host.tunnel.resolve_tunnel_token", return_value=None),
            pytest.raises(TunnelValidationError, match="Cloudflare Tunnel Token not found in OS Keyring"),
        ):
            validate_tunnel_prerequisites(tunnel_type="cloudflare", domain="valid.example.com", quick=False)


def test_validate_basic_auth_credentials_strict() -> None:
    # 1. Missing username or keyring account fails fast without fallback
    with pytest.raises(AuthGateValidationError, match="Incomplete Basic Auth Configuration"):
        validate_basic_auth_credentials(username=None, keyring_account="SOME_ACCT")

    with pytest.raises(AuthGateValidationError, match="Incomplete Basic Auth Configuration"):
        validate_basic_auth_credentials(username="admin", keyring_account=None)

    # 2. Password not found in keyring
    with (
        patch("pa_packages.tunnels.host.auth_gate.get_keyring_secret", return_value=None),
        pytest.raises(AuthGateValidationError, match="Basic Auth Password Not Found in OS Keyring"),
    ):
        validate_basic_auth_credentials(username="admin", keyring_account="MISSING_ACCT")

    # 3. Successful resolution
    with patch("pa_packages.tunnels.host.auth_gate.get_keyring_secret", return_value="secret123"):
        user, pwd = validate_basic_auth_credentials(username="admin", keyring_account="VALID_ACCT")
        assert user == "admin"
        assert pwd == "secret123"


def test_validate_oidc_config() -> None:
    # Missing client_id or client_secret_account
    with pytest.raises(AuthGateValidationError, match="Incomplete OIDC Configuration"):
        validate_oidc_config(provider="google", client_id=None, client_secret_account="SEC")

    with pytest.raises(AuthGateValidationError, match="Incomplete OIDC Configuration"):
        validate_oidc_config(provider="google", client_id="cid", client_secret_account=None)

    # Secret not in keyring
    with (
        patch("pa_packages.tunnels.host.auth_gate.get_keyring_secret", return_value=None),
        pytest.raises(AuthGateValidationError, match="OIDC Client Secret Not Found in OS Keyring"),
    ):
        validate_oidc_config(provider="google", client_id="cid", client_secret_account="MISSING")

    # Success
    with patch("pa_packages.tunnels.host.auth_gate.get_keyring_secret", return_value="gocspx-secret"):
        cfg = validate_oidc_config(
            provider="google",
            client_id="cid.apps.googleusercontent.com",
            client_secret_account="GOOGLE_CLIENT_SECRET",
            email_domains=["company.com"],
        )
        assert cfg["provider"] == "google"
        assert cfg["client_secret"] == "gocspx-secret"
        assert cfg["email_domains"] == ["company.com"]


def test_token_gate_manager_http_flow() -> None:
    import urllib.error
    import urllib.request

    with ExitStack() as stack:
        # Dummy upstream listening server
        import socket
        import threading

        upstream_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        upstream_sock.bind(("127.0.0.1", 0))
        upstream_sock.listen(1)
        upstream_port = upstream_sock.getsockname()[1]

        def _upstream_handler() -> None:
            with contextlib.suppress(Exception):
                conn, _ = upstream_sock.accept()
                req = conn.recv(1024)
                if b"GET /" in req:
                    conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 12\r\n\r\nUpstream OK!")
                conn.close()

        threading.Thread(target=_upstream_handler, daemon=True).start()
        stack.callback(upstream_sock.close)

        # Start Token Gate
        gate = TokenGateManager(upstream_port=upstream_port, title="Test Gate")
        gate_port = gate.start(stack)

        # 1. Unauthenticated request -> 401
        req = urllib.request.Request(f"http://127.0.0.1:{gate_port}/")
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req, timeout=5)
        assert exc.value.code == 401

        # 2. Magic token request -> 302 redirect with session cookie
        magic_url = f"http://127.0.0.1:{gate_port}/?pa_token={gate.token}"

        # Opener that doesn't follow redirects automatically
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None

        opener = urllib.request.build_opener(NoRedirect)
        try:
            resp = opener.open(magic_url, timeout=5)
            assert resp.code == 302
            cookie_hdr = resp.headers.get("Set-Cookie", "")
            assert "pa_session=" in cookie_hdr
        except urllib.error.HTTPError as e:
            assert e.code == 302
            cookie_hdr = e.headers.get("Set-Cookie", "")
            assert "pa_session=" in cookie_hdr


def test_tunnel_service_multi_endpoint_and_auth_policy() -> None:
    with ExitStack() as stack:
        svc = TunnelService(
            provider="cloudflare",
            quick=True,
            auth_mode="token",
        )

        with (
            patch("pa_packages.tunnels.host.tunnel.CloudflareTunnelManager.start_endpoint") as mock_cf,
            patch("pa_packages.tunnels.host.auth_gate.TokenGateManager.start") as mock_gate,
        ):
            mock_cf.side_effect = [
                ("https://t3-quick.trycloudflare.com", "t3-quick.trycloudflare.com"),
                ("https://desktop-quick.trycloudflare.com", "desktop-quick.trycloudflare.com"),
            ]
            mock_gate.return_value = 16080

            # Register T3 (Intrinsic)
            svc.register_service(
                TunnelEndpointRequest(
                    service_name="t3",
                    port=3773,
                    auth_policy=IngressAuthPolicy.INTRINSIC,
                )
            )

            # Register Desktop (Required)
            svc.register_service(
                TunnelEndpointRequest(
                    service_name="desktop",
                    port=6080,
                    auth_policy=IngressAuthPolicy.REQUIRED,
                )
            )

            endpoints = svc.provision_all(stack)
            assert len(endpoints) == 2

            # T3 is not gated (intrinsic)
            assert endpoints["t3"].is_gated is False
            assert endpoints["t3"].auth_mode == "intrinsic"
            assert endpoints["t3"].public_url == "https://t3-quick.trycloudflare.com"

            # Desktop is gated (token gate)
            assert endpoints["desktop"].is_gated is True
            assert endpoints["desktop"].auth_mode == "token"
            assert endpoints["desktop"].public_url == "https://desktop-quick.trycloudflare.com"
            assert endpoints["desktop"].access_token is not None


def test_tunnels_plugin_lifecycle(tmp_path: Path) -> None:
    from cli import RunOptions

    plugin = TunnelsPlugin(manifest=None, package_dir=tmp_path, project_dir=tmp_path)  # type: ignore[arg-type]
    ctx = RunContext(
        project_dir=tmp_path,
        options=RunOptions(extra_options={"tunnel": "cloudflare", "tunnel_quick": True}),
        config={},  # type: ignore[arg-type]
    )

    plugin.on_run_init(ctx)
    assert ctx.has_mode("tunnels")
    assert ctx.tunnel_provider is not None
    assert ctx.tunnel_provider.is_enabled() is True

    # Preflight
    with patch("pa_packages.tunnels.host.plugin.validate_tunnel_prerequisites"):
        plugin.on_preflight(ctx)
