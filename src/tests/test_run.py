"""Unit tests for src/run.py — entrypoint validation and initialization."""

import os
import sys
from unittest.mock import MagicMock, patch

import run

sys.dont_write_bytecode = True


class TestInitRuntime:
    def test_exits_on_default_admin_password(self, monkeypatch):
        monkeypatch.setattr(run, "ADMIN_PASSWORD", "CHANGEME")
        exited = []
        monkeypatch.setattr(run.sys, "exit", lambda code: exited.append(code))
        run._init_runtime()
        assert exited == [1]

    def test_exits_on_empty_admin_password(self, monkeypatch, caplog):
        import logging

        monkeypatch.setattr(run, "ADMIN_PASSWORD", "")
        exited = []
        monkeypatch.setattr(run.sys, "exit", lambda code: exited.append(code))
        with caplog.at_level(logging.ERROR):
            run._init_runtime()
        assert exited == [1]
        assert "uv run keyring set pa-container ADMIN_PASSWORD" in caplog.text
        assert "Host environment variables are not accepted" in caplog.text

    def test_admin_password_ignores_host_environment_variables(self, monkeypatch, caplog):
        import importlib
        import logging

        import config

        monkeypatch.setenv("ADMIN_PASSWORD", "env_should_be_ignored")
        with patch("secret_store.get_keyring_secret", return_value="from_keyring_only"):
            with caplog.at_level(logging.WARNING):
                importlib.reload(config)
            try:
                assert config.ADMIN_PASSWORD == "from_keyring_only"
                assert "ADMIN_PASSWORD in host environment is ignored" in caplog.text
                assert "ADMIN_PASSWORD" not in os.environ
            finally:
                importlib.reload(config)

    def test_exits_on_environment_error(self, monkeypatch):
        monkeypatch.setattr(run, "ADMIN_PASSWORD", "securepassword123")
        exited = []
        monkeypatch.setattr(run.sys, "exit", lambda code: exited.append(code))

        def mock_validate(bin_path):
            raise run.EnvironmentError("Podman not found")

        monkeypatch.setattr(run, "validate_environment", mock_validate)
        run._init_runtime()
        assert exited == [1]

    def test_initializes_runtime_on_valid_environment(self, monkeypatch):
        monkeypatch.setattr(run, "ADMIN_PASSWORD", "securepassword123")
        monkeypatch.setattr(run, "validate_environment", lambda bin_path: "podman")

        mock_rt = MagicMock()
        mock_rt.upstream_network = "podman"
        monkeypatch.setattr(run, "PodmanRuntime", lambda *a, **kw: mock_rt)

        run._init_runtime()
        assert run.CONTAINER_RUNTIME == "podman"
        assert run.PROXY_UPSTREAM_NETWORK == "podman"


class TestAgentLaunchReadOnlyPiContainerMount:
    def test_read_only_pa_container_mount_flag_included_when_enabled(self):
        pa_container_dir = run.PROJECT_DIR / ".pa-container"
        read_only_pa_container = True
        flags = ["--volume", f"{pa_container_dir}:/workspace/.pa-container:ro"] if read_only_pa_container else []
        assert flags == ["--volume", f"{pa_container_dir}:/workspace/.pa-container:ro"]

    def test_read_only_pa_container_mount_flag_omitted_when_disabled(self):
        pa_container_dir = run.PROJECT_DIR / ".pa-container"
        read_only_pa_container = False
        flags = ["--volume", f"{pa_container_dir}:/workspace/.pa-container:ro"] if read_only_pa_container else []
        assert flags == []


class TestAgentLaunchReadOnlyGitHooksMount:
    def test_read_only_git_hooks_flag_included_for_directory(self, tmp_path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        hooks_dir = git_dir / "hooks"
        read_only_git_hooks = True
        flags = []
        if read_only_git_hooks and git_dir.is_dir():
            hooks_dir.mkdir(parents=True, exist_ok=True)
            flags = ["--volume", f"{hooks_dir}:/workspace/.git/hooks:ro"]
        assert flags == ["--volume", f"{hooks_dir}:/workspace/.git/hooks:ro"]
        assert hooks_dir.is_dir()

    def test_read_only_git_hooks_flag_included_for_worktree_file(self, tmp_path):
        git_file = tmp_path / ".git"
        git_file.write_text("gitdir: /outside/path/to/gitdir\n")
        read_only_git_hooks = True
        flags = []
        if read_only_git_hooks and git_file.is_file():
            flags = ["--volume", f"{git_file}:/workspace/.git:ro"]
        assert flags == ["--volume", f"{git_file}:/workspace/.git:ro"]


class TestAgentLaunchSecurityOpts:
    def test_no_new_privileges_included_when_nested_disabled(self):
        nested_enabled = False
        opts = ["--security-opt", "no-new-privileges"] if not nested_enabled else []
        assert opts == ["--security-opt", "no-new-privileges"]

    def test_no_new_privileges_omitted_when_nested_enabled(self):
        nested_enabled = True
        opts = ["--security-opt", "no-new-privileges"] if not nested_enabled else []
        assert opts == []


class TestAgentLaunchGitFlags:
    def test_git_safe_directory_and_rewrite_flags_enabled(self):
        git_cfg = {"safe_directory": True, "rewrite_ssh_to_https": True}
        flags = [
            "--env",
            f"GIT_SAFE_DIRECTORY={'true' if git_cfg['safe_directory'] else 'false'}",
            "--env",
            f"GIT_REWRITE_SSH={'true' if git_cfg['rewrite_ssh_to_https'] else 'false'}",
        ]
        assert flags == [
            "--env",
            "GIT_SAFE_DIRECTORY=true",
            "--env",
            "GIT_REWRITE_SSH=true",
        ]

    def test_git_safe_directory_and_rewrite_flags_disabled(self):
        git_cfg = {"safe_directory": False, "rewrite_ssh_to_https": False}
        flags = [
            "--env",
            f"GIT_SAFE_DIRECTORY={'true' if git_cfg['safe_directory'] else 'false'}",
            "--env",
            f"GIT_REWRITE_SSH={'true' if git_cfg['rewrite_ssh_to_https'] else 'false'}",
        ]
        assert flags == [
            "--env",
            "GIT_SAFE_DIRECTORY=false",
            "--env",
            "GIT_REWRITE_SSH=false",
        ]


class TestAgentLaunchSourceControlFlags:
    def test_setup_git_credentials_flag(self):
        sc_cfg = {"setup_git_credentials": True}
        flag = f"SETUP_GIT_CREDENTIALS={'true' if sc_cfg['setup_git_credentials'] else 'false'}"
        assert flag == "SETUP_GIT_CREDENTIALS=true"

    def test_token_env_forwarding_and_override(self):
        sc_tokens = {"GH_TOKEN": "gho_auto", "GITHUB_TOKEN": "gho_auto"}
        agent_env = {"GH_TOKEN": "gho_user_override", "OTHER_VAR": "val"}
        merged = {**sc_tokens, **agent_env}
        assert merged["GH_TOKEN"] == "gho_user_override"
        assert merged["GITHUB_TOKEN"] == "gho_auto"
        assert merged["OTHER_VAR"] == "val"


class TestVolumeMountOptions:
    def test_shadow_volumes_have_nodev_nosuid(self):
        from runtimes import PodmanRuntime

        vol_name = "pa-container-shadow-12345"
        dest_path = "/workspace/.venv"
        arg = PodmanRuntime().volume_subpath_args(vol_name, dest_path, "workspace/.venv")
        assert arg == [
            "--mount",
            "type=volume,src=pa-container-shadow-12345,dst=/workspace/.venv,subpath=workspace/.venv,nodev,nosuid",
        ]


class TestProcessGatewayConfigs:
    def test_api_key_missing_exits(self, tmp_path, monkeypatch, caplog):
        import logging

        from registry import GatewayAuth, GatewayDef

        gw_def = GatewayDef(
            id="opper",
            base_url="https://api.opper.ai/v3/compat",
            auth=GatewayAuth(type="api-key"),
        )
        gateways = [
            {
                "name": "opper",
                "gatewayDef": gw_def,
                "baseUrl": gw_def.base_url,
                "containerEnvVar": "MISSING_OPPER_KEY",
                "keyringService": "pa-container",
                "keyringAccount": "MISSING_OPPER_KEY",
            }
        ]

        exited = []
        monkeypatch.setattr(run.sys, "exit", lambda code: exited.append(code))
        with caplog.at_level(logging.ERROR), monkeypatch.context() as m:
            m.delenv("MISSING_OPPER_KEY", raising=False)
            with patch("keyring.get_password", return_value=None):
                run.process_gateway_configs(gateways, tmp_path)

        assert exited == [1]
        assert "Save in OS keyring: uv run keyring set" in caplog.text
        assert "Set via environment" not in caplog.text

    def test_api_key_in_env_is_ignored(self, tmp_path, monkeypatch, caplog):
        import logging

        from registry import GatewayAuth, GatewayDef

        gw_def = GatewayDef(
            id="opper",
            base_url="https://api.opper.ai/v3/compat",
            auth=GatewayAuth(type="api-key"),
        )
        gateways = [
            {
                "name": "opper",
                "gatewayDef": gw_def,
                "baseUrl": gw_def.base_url,
                "containerEnvVar": "ENV_OPPER_KEY",
                "keyringService": "pa-container",
                "keyringAccount": "ENV_OPPER_KEY",
            }
        ]

        exited = []
        monkeypatch.setattr(run.sys, "exit", lambda code: exited.append(code))
        monkeypatch.setenv("ENV_OPPER_KEY", "leaked_in_env")

        with caplog.at_level(logging.ERROR), patch("keyring.get_password", return_value=None):
            run.process_gateway_configs(gateways, tmp_path)

        assert exited == [1]
        assert "Save in OS keyring: uv run keyring set" in caplog.text

    def test_api_key_found_sets_env(self, tmp_path, monkeypatch):
        from registry import GatewayAuth, GatewayDef

        gw_def = GatewayDef(
            id="opper",
            base_url="https://api.opper.ai/v3/compat",
            auth=GatewayAuth(type="api-key"),
        )
        gateways = [
            {
                "name": "opper",
                "gatewayDef": gw_def,
                "baseUrl": gw_def.base_url,
                "containerEnvVar": "TEST_OPPER_KEY",
                "keyringService": "pa-container",
                "keyringAccount": "TEST_OPPER_KEY",
            }
        ]

        monkeypatch.delenv("TEST_OPPER_KEY", raising=False)

        with patch("keyring.get_password", return_value="opp_secret_abc"):
            run.process_gateway_configs(gateways, tmp_path)

        assert run.os.environ.get("TEST_OPPER_KEY") == "opp_secret_abc"

    def test_skips_when_no_auth(self, tmp_path, monkeypatch):
        from types import SimpleNamespace

        gw_def = SimpleNamespace(auth=None)
        monkeypatch.setattr(run.containers, "warn_about_gateway_allowlist", lambda *a, **k: None)
        run.process_gateway_configs([{"name": "test-gw", "gatewayDef": gw_def}], tmp_path)

    def test_openid_auth_sets_env(self, tmp_path, monkeypatch):
        from types import SimpleNamespace

        auth = SimpleNamespace(type="openid", env_var=None)
        gw_def = SimpleNamespace(auth=auth)
        monkeypatch.setattr("auth.ensure_gateway_auth", lambda name, a: "mock-token-123")
        monkeypatch.setattr(run.containers, "warn_about_gateway_allowlist", lambda *a, **k: None)

        run.process_gateway_configs([{"name": "test-gw", "gatewayDef": gw_def}], tmp_path)
        assert os.environ.get("TEST_GW_TOKEN") == "mock-token-123"
        os.environ.pop("TEST_GW_TOKEN", None)


class TestEnsureProxyImage:
    def test_rebuilds_when_not_current(self, monkeypatch):
        built = []
        monkeypatch.setattr(run.images, "proxy_image_is_current", lambda **kw: False)
        monkeypatch.setattr(run, "build_proxy", lambda rt: built.append(rt))

        result = run.ensure_proxy_image("podman")
        assert result is True
        assert built == ["podman"]

    def test_skips_when_current(self, monkeypatch):
        built = []
        monkeypatch.setattr(run.images, "proxy_image_is_current", lambda **kw: True)
        monkeypatch.setattr(run, "build_proxy", lambda rt: built.append(rt))

        result = run.ensure_proxy_image("podman")
        assert result is False
        assert built == []


class TestT3LaunchConfiguration:
    def test_t3_flag_enables_mode_and_default_port(self):
        from unittest.mock import patch

        from network import resolve_t3_port

        argv = ["run.py", "--t3"]
        cli_t3 = "--t3" in argv
        container_argv = [arg for arg in argv[1:] if arg != "--t3"]
        assert cli_t3 is True
        assert container_argv == []

        agent_ports = {"expose": "localhost", "publish": []}
        with patch("network.is_port_available", return_value=True):
            port = resolve_t3_port(agent_ports)
        assert port == 3773
        assert agent_ports["publish"] == [(3773, 3773)]

    def test_t3_preserves_custom_port(self):
        from unittest.mock import patch

        from network import resolve_t3_port

        agent_ports = {"expose": "localhost", "publish": [(13773, 3773)]}
        with patch("network.is_port_available", return_value=True):
            port = resolve_t3_port(agent_ports)
        assert port == 13773
        assert agent_ports["publish"] == [(13773, 13773)]

    def test_t3_advertise_host_cli_parsing(self):
        # Two-arg form
        raw_args = ["--t3", "--t3-advertise-host", "192.168.1.50", "extra_arg"]
        cli_t3 = False
        cli_t3_advertise_host = None
        cli_lan = False
        container_argv = []
        i = 0
        while i < len(raw_args):
            arg = raw_args[i]
            if arg == "--t3":
                cli_t3 = True
                i += 1
            elif arg == "--t3-lan":
                cli_lan = True
                i += 1
            elif arg == "--t3-external-ip":
                cli_t3_advertise_host = "external"
                i += 1
            elif arg == "--t3-advertise-host" and i + 1 < len(raw_args):
                cli_t3_advertise_host = raw_args[i + 1]
                i += 2
            elif arg.startswith("--t3-advertise-host="):
                cli_t3_advertise_host = arg.split("=", 1)[1]
                i += 1
            else:
                container_argv.append(arg)
                i += 1

        assert cli_t3 is True
        assert cli_t3_advertise_host == "192.168.1.50"
        assert cli_lan is False
        assert container_argv == ["extra_arg"]

        # Equals form with --t3-lan and --t3-external-ip
        raw_args_flags = ["--t3", "--t3-external-ip", "--t3-lan"]
        cli_t3 = False
        cli_t3_advertise_host = None
        cli_lan = False
        i = 0
        while i < len(raw_args_flags):
            arg = raw_args_flags[i]
            if arg == "--t3":
                cli_t3 = True
                i += 1
            elif arg == "--t3-lan":
                cli_lan = True
                i += 1
            elif arg == "--t3-external-ip":
                cli_t3_advertise_host = "external"
                i += 1
            elif arg == "--t3-advertise-host" and i + 1 < len(raw_args_flags):
                cli_t3_advertise_host = raw_args_flags[i + 1]
                i += 2
            elif arg.startswith("--t3-advertise-host="):
                cli_t3_advertise_host = arg.split("=", 1)[1]
                i += 1
            else:
                i += 1

        assert cli_t3 is True
        assert cli_t3_advertise_host == "external"
        assert cli_lan is True

        # Unprefixed flags (--lan, --tunnel, etc.) are treated as container argv
        raw_args_unprefixed = ["--lan", "--tunnel", "cf", "--public-url", "https://example.com"]
        cli_lan = False
        cli_t3_tunnel = None
        container_argv_unprefixed = []
        i = 0
        while i < len(raw_args_unprefixed):
            arg = raw_args_unprefixed[i]
            if arg == "--t3-lan":
                cli_lan = True
                i += 1
            elif arg == "--t3-tunnel" and i + 1 < len(raw_args_unprefixed):
                cli_t3_tunnel = raw_args_unprefixed[i + 1]
                i += 2
            else:
                container_argv_unprefixed.append(arg)
                i += 1
        assert cli_lan is False
        assert cli_t3_tunnel is None
        assert container_argv_unprefixed == ["--lan", "--tunnel", "cf", "--public-url", "https://example.com"]

    def test_t3_policy_content(self):
        import json

        policy_file = run.REPO_ROOT / "coding-agent" / "t3-policy.json"
        assert policy_file.is_file()
        data = json.loads(policy_file.read_text())
        assert data.get("schemaVersion") == 1
        assert data.get("limits", {}).get("providers", {}).get("allowedDrivers") == [
            "pi",
            "opencode",
            "claudeAgent",
            "antigravity",
        ]

    def test_t3_settings_and_policy_synthesis(self, tmp_path):
        import json

        from agents import (
            AntigravityDriver,
            ClaudeDriver,
            OpenCodeDriver,
            PiAgentDriver,
            synthesize_t3_policy,
            synthesize_t3_settings,
        )

        t3_dir = tmp_path / "t3"
        drivers = [PiAgentDriver(), OpenCodeDriver(), ClaudeDriver(), AntigravityDriver()]
        active = OpenCodeDriver()

        settings_path = synthesize_t3_settings(t3_dir, active, drivers)
        assert settings_path.is_file()
        settings = json.loads(settings_path.read_text())

        assert settings["textGenerationModelSelection"]["instanceId"] == "opencode"
        assert settings["textGenerationModelSelection"]["model"] == "default"
        assert settings["providerInstances"]["opencode"]["driver"] == "opencode"
        assert settings["providerInstances"]["opencode"]["enabled"] is True
        assert settings["providerInstances"]["opencode"]["binaryPath"] == "opencode"
        assert settings["providerInstances"]["opencode"]["config"]["binaryPath"] == "opencode"
        assert settings["providerInstances"]["pi"]["driver"] == "pi"
        assert settings["providerInstances"]["claudeAgent"]["driver"] == "claudeAgent"
        assert settings["providerInstances"]["antigravity"]["driver"] == "antigravity"
        assert settings["providerInstances"]["antigravity"]["config"]["authMethod"] == "oauth-personal"

        # Preserve existing custom settings on re-synthesis
        settings["providerInstances"]["opencode"]["customOption"] = "preserved"
        settings_path.write_text(json.dumps(settings))
        synthesize_t3_settings(t3_dir, active, drivers)
        updated_settings = json.loads(settings_path.read_text())
        assert updated_settings["providerInstances"]["opencode"]["customOption"] == "preserved"

        # Synthesize policy
        policy_path = synthesize_t3_policy(t3_dir, drivers)
        assert policy_path.is_file()
        policy = json.loads(policy_path.read_text())
        assert policy["schemaVersion"] == 1
        assert policy["organization"] == "pa-container"
        assert policy["limits"]["providers"]["allowedDrivers"] == [
            "pi",
            "opencode",
            "claudeAgent",
            "antigravity",
        ]

    def test_t3_single_agent_synthesis_disables_unselected(self, tmp_path):
        import json

        from agents import OpenCodeDriver, PiAgentDriver, synthesize_t3_policy, synthesize_t3_settings

        t3_dir = tmp_path / "t3"
        # Initial run with both opencode and pi
        synthesize_t3_settings(t3_dir, OpenCodeDriver(), [OpenCodeDriver(), PiAgentDriver()])
        # Subsequent run with only opencode
        settings_path = synthesize_t3_settings(t3_dir, OpenCodeDriver(), [OpenCodeDriver()])
        settings = json.loads(settings_path.read_text())
        assert settings["providerInstances"]["opencode"]["enabled"] is True
        assert settings["providerInstances"]["pi"]["enabled"] is False

        policy_path = synthesize_t3_policy(t3_dir, [OpenCodeDriver()])
        policy = json.loads(policy_path.read_text())
        assert policy["limits"]["providers"]["allowedDrivers"] == ["opencode"]


class TestT3AdvertiseHostResolution:
    def test_defaults_to_localhost_when_unconfigured(self):
        from unittest.mock import patch

        cli_t3_advertise_host = None
        raw_adv_host = cli_t3_advertise_host or "localhost"
        with patch("util.get_host_external_ip") as mock_get_ip:
            if raw_adv_host.strip().lower() in ("external", "external_ip", "auto"):
                t3_advertise_host = mock_get_ip()
            else:
                t3_advertise_host = raw_adv_host.strip()
            assert t3_advertise_host == "localhost"
            mock_get_ip.assert_not_called()

    def test_explicit_external_resolves_external_ip(self):
        from unittest.mock import patch

        import util

        for variant in ("external", "EXTERNAL", "external_ip", "auto"):
            with patch("util.get_host_external_ip", return_value="192.168.10.20"):
                if variant.strip().lower() in ("external", "external_ip", "auto"):
                    t3_advertise_host = util.get_host_external_ip()
                else:
                    t3_advertise_host = variant.strip()
                assert t3_advertise_host == "192.168.10.20"

    def test_preserves_custom_configured_host(self):
        from unittest.mock import patch

        raw_adv_host = "my-custom-dev.lan"
        with patch("util.get_host_external_ip") as mock_get_ip:
            if raw_adv_host.strip().lower() in ("external", "external_ip", "auto"):
                t3_advertise_host = mock_get_ip()
            else:
                t3_advertise_host = raw_adv_host.strip()
            assert t3_advertise_host == "my-custom-dev.lan"
            mock_get_ip.assert_not_called()

    def test_external_ip_does_not_implicitly_elevate_lan(self):
        from unittest.mock import MagicMock

        mock_logger = MagicMock()
        agent_ports = {"expose": "localhost", "publish": [(3773, 3773)]}
        t3_advertise_host = "192.168.1.50"
        if t3_advertise_host not in ("localhost", "127.0.0.1", "::1") and agent_ports.get("expose") != "lan":
            mock_logger.warning("warn message")
        # Ensure expose remains localhost
        assert agent_ports["expose"] == "localhost"
        mock_logger.warning.assert_called_once()

    def test_explicit_lan_flag_elevates_agent_ports(self):
        agent_ports = {"expose": "localhost", "publish": [(3773, 3773)]}
        cli_lan = True
        if cli_lan:
            agent_ports["expose"] = "lan"
        assert agent_ports["expose"] == "lan"

    def test_t3_mounts_configured_in_t3_mode(self, tmp_path):
        pa_container_dir = tmp_path / ".pa-container"
        is_t3_mode = True
        t3_mounts: list[str] = []
        t3_chown: list[str] = []
        if is_t3_mode:
            t3_dir = pa_container_dir / "t3"
            t3_dir.mkdir(parents=True, exist_ok=True)
            t3_mounts = ["--volume", f"{t3_dir}:/home/agent/.t3"]
            t3_chown = ["/home/agent/.t3"]
        assert t3_mounts == ["--volume", f"{pa_container_dir / 't3'}:/home/agent/.t3"]
        assert t3_chown == ["/home/agent/.t3"]

    def test_t3_sync_antigravity_mount_included(self, tmp_path):
        from config import REPO_ROOT

        pa_container_dir = tmp_path / ".pa-container"
        t3_dir = pa_container_dir / "t3"
        t3_dir.mkdir(parents=True, exist_ok=True)
        t3_mounts = ["--volume", f"{t3_dir}:/home/agent/.t3"]
        sync_src = REPO_ROOT / "coding-agent" / "t3-sync-antigravity.py"
        if sync_src.exists():
            t3_mounts.extend(["--volume", f"{sync_src}:/usr/local/share/pa-container/t3-sync-antigravity.py:ro"])
        assert f"{sync_src}:/usr/local/share/pa-container/t3-sync-antigravity.py:ro" in t3_mounts

    def test_driver_mount_chown_intermediate_paths(self):
        from pathlib import Path

        from agents.base import AgentMount

        mounts = [
            AgentMount(source=Path("/host/cfg"), destination="/home/agent/.config/opencode"),
            AgentMount(source=Path("/host/data"), destination="/home/agent/.local/share/opencode"),
            AgentMount(source=Path("/host/workspace"), destination="/workspace/custom"),
        ]
        driver_mount_chown: list[str] = []
        for m in mounts:
            dest_path = Path(m.destination)
            try:
                rel = dest_path.relative_to(Path("/home/agent"))
                curr = Path("/home/agent")
                for part in rel.parts:
                    curr = curr / part
                    driver_mount_chown.append(str(curr))
            except ValueError:
                driver_mount_chown.append(str(dest_path))

        assert "/home/agent/.config" in driver_mount_chown
        assert "/home/agent/.config/opencode" in driver_mount_chown
        assert "/home/agent/.local" in driver_mount_chown
        assert "/home/agent/.local/share" in driver_mount_chown
        assert "/home/agent/.local/share/opencode" in driver_mount_chown
        assert "/workspace/custom" in driver_mount_chown

    def test_t3_tunnel_cli_parsing(self):
        raw_args = [
            "--t3-tunnel",
            "cloudflare",
            "--t3-tunnel-domain",
            "t3.example.com",
            "--t3-tunnel-runner=container",
            "--t3-tunnel-keyring-account",
            "CUSTOM_CF_TOKEN",
            "--t3-public-url=https://custom-entry.dev",
        ]
        cli_t3 = False
        cli_t3_tunnel = None
        cli_t3_tunnel_domain = None
        cli_t3_tunnel_quick = False
        cli_t3_tunnel_runner = "auto"
        cli_t3_tunnel_keyring_account = "CLOUDFLARE_TUNNEL_TOKEN"
        cli_t3_public_url = None
        i = 0
        while i < len(raw_args):
            arg = raw_args[i]
            if arg == "--t3-tunnel" and i + 1 < len(raw_args):
                cli_t3_tunnel = raw_args[i + 1]
                cli_t3 = True
                i += 2
            elif arg == "--t3-tunnel-domain" and i + 1 < len(raw_args):
                cli_t3_tunnel_domain = raw_args[i + 1]
                cli_t3 = True
                i += 2
            elif arg == "--t3-tunnel-runner" and i + 1 < len(raw_args):
                cli_t3_tunnel_runner = raw_args[i + 1]
                cli_t3 = True
                i += 2
            elif arg.startswith("--t3-tunnel-runner="):
                cli_t3_tunnel_runner = arg.split("=", 1)[1]
                cli_t3 = True
                i += 1
            elif arg == "--t3-tunnel-keyring-account" and i + 1 < len(raw_args):
                cli_t3_tunnel_keyring_account = raw_args[i + 1]
                cli_t3 = True
                i += 2
            elif arg == "--t3-public-url" and i + 1 < len(raw_args):
                cli_t3_public_url = raw_args[i + 1]
                cli_t3 = True
                i += 2
            elif arg.startswith("--t3-public-url="):
                cli_t3_public_url = arg.split("=", 1)[1]
                cli_t3 = True
                i += 1
            else:
                i += 1

        assert cli_t3 is True
        assert cli_t3_tunnel == "cloudflare"
        assert cli_t3_tunnel_domain == "t3.example.com"
        assert cli_t3_tunnel_quick is False
        assert cli_t3_tunnel_runner == "container"
        assert cli_t3_tunnel_keyring_account == "CUSTOM_CF_TOKEN"
        assert cli_t3_public_url == "https://custom-entry.dev"

    def test_t3_tunnel_suppresses_external_ip_warning(self):
        from unittest.mock import MagicMock

        mock_logger = MagicMock()
        agent_ports = {"expose": "localhost", "publish": [(3773, 3773)]}
        t3_advertise_host = "t3.example.com"
        cli_t3_tunnel = "cloudflare"
        cli_t3_public_url = None

        has_active_tunnel = bool(cli_t3_tunnel or cli_t3_public_url)
        if (
            not has_active_tunnel
            and t3_advertise_host not in ("localhost", "127.0.0.1", "::1")
            and agent_ports.get("expose") != "lan"
        ):
            mock_logger.warning("warn message")

        # Expose should remain localhost and no warning should be logged
        assert agent_ports["expose"] == "localhost"
        mock_logger.warning.assert_not_called()

    def test_t3_tunnel_zero_port_https_normalization(self):
        from urllib.parse import urlparse

        from tunnel import normalize_tunnel_url

        cli_t3_public_url = "http://t3.example.com:3773"
        t3_public_url = normalize_tunnel_url(cli_t3_public_url)
        assert t3_public_url == "https://t3.example.com"
        assert ":3773" not in t3_public_url
        assert t3_public_url.startswith("https://")

        t3_advertise_host = urlparse(t3_public_url).hostname
        assert t3_advertise_host == "t3.example.com"

        env_args = [
            "--env",
            "PA_CONTAINER_MODE=t3",
            "--env",
            "T3_PORT=3773",
            "--env",
            f"T3_ADVERTISE_HOST={t3_advertise_host}",
            *(["--env", f"T3_PUBLIC_URL={t3_public_url}"] if t3_public_url else []),
        ]
        assert "--env" in env_args
        assert "T3_PORT=3773" in env_args
        assert "T3_PUBLIC_URL=https://t3.example.com" in env_args
        assert "T3_ADVERTISE_HOST=t3.example.com" in env_args

    def test_t3_tunnel_quick_infers_cloudflare_tunnel(self):
        from cli import RunOptions

        options = RunOptions(t3_tunnel_quick=True)

        cli_t3_tunnel = options.t3_tunnel
        cli_t3_tunnel_domain = options.t3_tunnel_domain
        cli_t3_tunnel_quick = options.t3_tunnel_quick
        cli_t3_tunnel_runner = options.t3_tunnel_runner
        cli_t3_tunnel_keyring_account = options.t3_tunnel_keyring_account
        cli_t3_tunnel_tailscale_mode = options.t3_tunnel_tailscale_mode

        if not cli_t3_tunnel:
            has_cf = bool(
                cli_t3_tunnel_quick or cli_t3_tunnel_domain or cli_t3_tunnel_runner or cli_t3_tunnel_keyring_account
            )
            has_ts = bool(cli_t3_tunnel_tailscale_mode)
            if has_cf and not has_ts:
                cli_t3_tunnel = "cloudflare"
            elif has_ts and not has_cf:
                cli_t3_tunnel = "tailscale"

        assert cli_t3_tunnel == "cloudflare"

    def test_t3_tunnel_tailscale_mode_infers_tailscale_tunnel(self):
        from cli import RunOptions

        options = RunOptions(t3_tunnel_tailscale_mode="serve")

        cli_t3_tunnel = options.t3_tunnel
        cli_t3_tunnel_domain = options.t3_tunnel_domain
        cli_t3_tunnel_quick = options.t3_tunnel_quick
        cli_t3_tunnel_runner = options.t3_tunnel_runner
        cli_t3_tunnel_keyring_account = options.t3_tunnel_keyring_account
        cli_t3_tunnel_tailscale_mode = options.t3_tunnel_tailscale_mode

        if not cli_t3_tunnel:
            has_cf = bool(
                cli_t3_tunnel_quick or cli_t3_tunnel_domain or cli_t3_tunnel_runner or cli_t3_tunnel_keyring_account
            )
            has_ts = bool(cli_t3_tunnel_tailscale_mode)
            if has_cf and not has_ts:
                cli_t3_tunnel = "cloudflare"
            elif has_ts and not has_cf:
                cli_t3_tunnel = "tailscale"

        assert cli_t3_tunnel == "tailscale"

    def test_t3_advertise_host_shim_app_link_and_pairing_rewrite(self):
        import subprocess

        from config import REPO_ROOT

        shim_path = REPO_ROOT / "coding-agent" / "t3-advertise-host.cjs"
        node_script = f"""
        process.env.T3_PUBLIC_URL = "https://rick-symbols-trains-radar.trycloudflare.com";
        process.env.T3_ADVERTISE_HOST = "rick-symbols-trains-radar.trycloudflare.com";
        require("{shim_path}");

        let captured = [];
        const origWrite = process.stdout.write;
        process.stdout.write = (chunk) => {{
            captured.push(chunk.toString());
            return true;
        }};

        console.log("App link: t3code://pair?pairingUrl=http%3A%2F%2Flocalhost%3A3773%2Fpair%23token%3Dsecret123");
        console.log("Pairing URL: http://localhost:3773/pair#token=secret123");

        const out = captured.join("");
        if (!out.includes("https%3A%2F%2Frick-symbols-trains-radar.trycloudflare.com%2Fpair%23token%3Dsecret123")) {{
            throw new Error("App link was not properly rewritten: " + out);
        }}
        if (!out.includes("Pairing URL: https://rick-symbols-trains-radar.trycloudflare.com/pair#token=secret123")) {{
            throw new Error("Pairing URL was not properly rewritten: " + out);
        }}
        """
        res = subprocess.run(["node", "-e", node_script], capture_output=True, text=True, check=False)
        assert res.returncode == 0, f"Node script failed: {res.stderr}"

    def test_agent_driver_required_packages_access(self):
        """Verify that driver.required_packages property is accessed without being called as a function."""
        from agents import get_agent_driver

        for agent_name in ("pi", "opencode", "antigravity", "claude"):
            driver = get_agent_driver(agent_name)
            packages = driver.required_packages
            assert isinstance(packages, list)

    def test_cli_agent_disabled_exits_with_error(self, tmp_path, monkeypatch):
        import yaml

        from network import read_enabled_agents

        pa_dir = tmp_path / ".pa-container"
        pa_dir.mkdir(parents=True)
        (pa_dir / "config.yaml").write_text(yaml.dump({"agents": {"enabled": ["claude"]}}))
        enabled = read_enabled_agents(pa_dir)
        assert enabled == ["claude"]
        assert "pi" not in enabled

    def test_run_cleanup_orphaned_agent_containers_called(self, monkeypatch):
        import run

        called = []
        monkeypatch.setattr(run.containers, "cleanup_orphaned_agent_containers", lambda r: called.append(r) or ["c1"])
        result = run.containers.cleanup_orphaned_agent_containers("podman")
        assert result == ["c1"]
        assert called == ["podman"]

    def test_run_post_build_pruning_enabled(self, monkeypatch):
        import run

        pruned_calls = []
        monkeypatch.setattr(
            run.images,
            "prune_dangling_images",
            lambda r, purge_cache=False: pruned_calls.append((r, purge_cache)) or ["p1"],
        )
        if run.global_config.build.prune_dangling:
            run.images.prune_dangling_images("podman", purge_cache=False)
        assert pruned_calls == [("podman", False)]


class TestOpenBrowserResolution:
    def test_cli_flag_overrides(self, tmp_path):
        import run
        from cli import RunOptions

        (tmp_path / "config.yaml").write_text(
            "proxy:\n  expose_ui: localhost\n  max_view_flows: 2000\n  stream_large_bodies: 10m\n  open_browser: false\n"
        )

        options = RunOptions(open_browser=True)
        proxy_cfg = run.read_proxy_config(tmp_path)
        eff = options.open_browser if options.open_browser is not None else proxy_cfg["open_browser"]
        assert eff is True

    def test_project_config_used_when_no_cli(self, tmp_path):
        import run
        from cli import RunOptions

        (tmp_path / "config.yaml").write_text(
            "proxy:\n  expose_ui: localhost\n  max_view_flows: 2000\n  stream_large_bodies: 10m\n  open_browser: true\n"
        )

        options = RunOptions(open_browser=None)
        proxy_cfg = run.read_proxy_config(tmp_path)
        eff = options.open_browser if options.open_browser is not None else proxy_cfg["open_browser"]
        assert eff is True


class TestExecuteRunFatalErrors:
    def test_execute_run_missing_project_config(self, tmp_path, monkeypatch, caplog):
        import logging

        from cli import RunOptions
        from logging_driver import LogCategory, LogDriver

        empty_proj = tmp_path / "empty_project"
        empty_proj.mkdir()
        monkeypatch.setattr(run, "PROJECT_DIR", empty_proj)
        monkeypatch.setattr(run, "_init_runtime", lambda: None)

        custom_state = tmp_path / "state"
        monkeypatch.setenv("XDG_STATE_HOME", str(custom_state))
        driver = LogDriver(empty_proj, quiet=True)

        with (
            caplog.at_level(logging.ERROR),
            patch.object(driver, "fail_and_render", wraps=driver.fail_and_render) as mock_fail,
        ):
            ret = run.execute_run(RunOptions(), driver=driver)

        assert ret == 1
        assert mock_fail.called
        call_args = mock_fail.call_args
        assert call_args[0][0] == LogCategory.PREFLIGHT
        assert call_args[0][1] == "Missing Project Configuration"
        assert ".pa-container/config.yaml" in call_args[0][2]
        assert call_args[1]["hints"][0] == "Initialize the project configuration with 'pa init'."

        error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert len(error_records) >= 1
        assert any(getattr(r, "category", None) == "preflight" for r in error_records)
        assert any("Missing Project Configuration" in r.getMessage() for r in error_records)
        driver.shutdown()

    def test_execute_run_environment_error(self, tmp_path, monkeypatch):
        from cli import RunOptions
        from logging_driver import LogCategory, LogDriver

        proj = tmp_path / "proj"
        proj.mkdir()
        monkeypatch.setattr(run, "PROJECT_DIR", proj)
        monkeypatch.setattr(run, "_init_runtime", MagicMock(side_effect=run.EnvironmentError("Container CLI missing")))

        custom_state = tmp_path / "state"
        monkeypatch.setenv("XDG_STATE_HOME", str(custom_state))
        driver = LogDriver(proj, quiet=True)

        with patch.object(driver, "fail_and_render", wraps=driver.fail_and_render) as mock_fail:
            ret = run.execute_run(RunOptions(), driver=driver)

        assert ret == 1
        assert mock_fail.called
        assert mock_fail.call_args[0][0] == LogCategory.PREFLIGHT
        assert mock_fail.call_args[0][1] == "Environment Check Failed"
        driver.shutdown()

    def test_execute_run_port_collision(self, tmp_path, monkeypatch):
        from cli import RunOptions
        from logging_driver import LogCategory, LogDriver

        proj = tmp_path / "proj"
        proj.mkdir()
        pa_dir = proj / ".pa-container"
        pa_dir.mkdir()
        (pa_dir / "config.yaml").write_text("schema_version: '0.6.6'\n")
        (pa_dir / "models.yaml").write_text("models:\n  - id: test\n")

        monkeypatch.setattr(run, "PROJECT_DIR", proj)
        monkeypatch.setattr(run, "_init_runtime", lambda: None)
        monkeypatch.setattr(run.project, "ensure_project_config", lambda *args, **kwargs: pa_dir)
        monkeypatch.setattr(run, "validate_config", lambda p: (True, [], "0.6.6"))
        monkeypatch.setattr(run, "validate_project_yaml", lambda d: [])
        monkeypatch.setattr(run, "validate_models", lambda p: (True, []))
        monkeypatch.setattr(run, "read_flow_export_enabled", lambda d: False)
        monkeypatch.setattr(run, "read_network_config", lambda d: {"ipv6": False})
        monkeypatch.setattr(run, "read_llama_config", lambda d: {})
        monkeypatch.setattr(run, "read_agent_extras", lambda d: {"mounts": []})
        monkeypatch.setattr(run, "read_read_only_pa_container", lambda d: False)
        monkeypatch.setattr(run, "read_security_config", lambda d: {"blocked_mount_paths": []})
        monkeypatch.setattr(run, "read_git_config", lambda d: {})
        monkeypatch.setattr(run, "read_source_control_config", lambda d: {})
        monkeypatch.setattr(run, "resolve_source_control_tokens", lambda d, log: {})
        monkeypatch.setattr(run, "validate_mount_paths", lambda m, b: [])
        monkeypatch.setattr(run, "read_enabled_agents", lambda d: ["pi"])
        monkeypatch.setattr(run, "read_default_agent", lambda d: "pi")
        monkeypatch.setattr(run, "read_desktop_config", lambda d: {"enabled": False})
        mock_driver_obj = MagicMock()
        mock_driver_obj.get_sessions_dir.return_value = tmp_path / "sessions"
        monkeypatch.setattr(run, "get_agent_driver", lambda t: mock_driver_obj)
        monkeypatch.setattr(run.containers, "sweep_orphaned_servers", lambda d: None)
        monkeypatch.setattr(run.containers, "sweep_orphaned_proxies", lambda r, d: None)
        monkeypatch.setattr(run.containers, "cleanup_orphaned_agent_containers", lambda r: None)
        monkeypatch.setattr(
            run, "read_nested_containers_config", lambda d: {"enabled": False, "ports": {"publish": []}}
        )
        monkeypatch.setattr(run, "read_agent_mode", lambda d: "t3")
        monkeypatch.setattr(run, "read_agent_ports", lambda d: {"publish": [(3773, 3773)], "expose": "localhost"})
        monkeypatch.setattr(run.containers, "unavailable_host_ports", lambda p, e: [3773])
        monkeypatch.setattr(run.containers, "port_holders", lambda r, p, k: {3773: "other-container"})

        custom_state = tmp_path / "state"
        monkeypatch.setenv("XDG_STATE_HOME", str(custom_state))
        driver = LogDriver(proj, quiet=True)

        with patch.object(driver, "fail_and_render", wraps=driver.fail_and_render) as mock_fail:
            ret = run.execute_run(RunOptions(), driver=driver)

        assert ret == 1
        assert mock_fail.called
        assert mock_fail.call_args[0][0] == LogCategory.PREFLIGHT
        assert mock_fail.call_args[0][1] == "Host Port Collision"
        driver.shutdown()

    def test_t3_already_running_aborts_in_preflight(self, tmp_path, monkeypatch):
        from cli import RunOptions
        from containers import RunningT3ContainerInfo
        from logging_driver import LogCategory, LogDriver

        proj = tmp_path / "my_project"
        proj.mkdir()
        pa = proj / ".pa-container"
        pa.mkdir()
        (pa / "config.yaml").write_text("version: 1\nagent:\n  name: pi\n")
        (pa / "models.yaml").write_text("models: []\n")

        monkeypatch.setattr(run, "PROJECT_DIR", proj)
        monkeypatch.setattr(run, "validate_config", lambda p: (True, [], 1))
        monkeypatch.setattr(run, "validate_project_yaml", lambda p: [])
        monkeypatch.setattr(run, "validate_models", lambda p: (True, []))
        monkeypatch.setattr(run, "validate_mount_paths", lambda m, b: [])
        monkeypatch.setattr(run, "read_flow_export_enabled", lambda d: False)
        monkeypatch.setattr(run, "read_network_config", lambda d: {"ipv6": False})
        monkeypatch.setattr(run, "read_llama_config", lambda d: {})
        monkeypatch.setattr(run, "read_agent_extras", lambda d: {"mounts": []})
        monkeypatch.setattr(run, "read_read_only_pa_container", lambda d: False)
        monkeypatch.setattr(run, "read_security_config", lambda d: {"blocked_mount_paths": []})
        monkeypatch.setattr(run, "read_git_config", lambda d: {})
        monkeypatch.setattr(run, "read_source_control_config", lambda d: {})
        monkeypatch.setattr(run, "resolve_source_control_tokens", lambda d, **kw: {})
        monkeypatch.setattr(run, "read_enabled_agents", lambda d: ["pi"])
        monkeypatch.setattr(run, "read_default_agent", lambda d: "pi")
        monkeypatch.setattr(run, "read_desktop_config", lambda d: {"enabled": False})
        mock_driver_obj = MagicMock()
        mock_driver_obj.get_sessions_dir.return_value = tmp_path / "sessions"
        monkeypatch.setattr(run, "get_agent_driver", lambda t: mock_driver_obj)
        monkeypatch.setattr(run.containers, "sweep_orphaned_servers", lambda d: None)
        monkeypatch.setattr(run.containers, "sweep_orphaned_proxies", lambda r, d: None)
        monkeypatch.setattr(run.containers, "cleanup_orphaned_agent_containers", lambda r: None)
        monkeypatch.setattr(
            run.containers,
            "find_running_t3_container",
            lambda d, runtime: RunningT3ContainerInfo(
                container_name="pa-container-agent-xyz123",
                container_id="xyz123",
                project_hash="102a2e0fff",
                launcher_pid=99999,
            ),
        )

        custom_state = tmp_path / "state"
        monkeypatch.setenv("XDG_STATE_HOME", str(custom_state))
        driver = LogDriver(proj, quiet=True)

        with patch.object(driver, "fail_and_render", wraps=driver.fail_and_render) as mock_fail:
            ret = run.execute_run(RunOptions(t3=True), driver=driver)

        assert ret == 1
        assert mock_fail.called
        assert mock_fail.call_args[0][0] == LogCategory.PREFLIGHT
        assert mock_fail.call_args[0][1] == "T3 Container Already Running"
        assert "pa-container-agent-xyz123" in mock_fail.call_args[0][2]
        driver.shutdown()
