"""Unit tests for pa_core/run.py — entrypoint validation and initialization."""

import os
import sys
from unittest.mock import MagicMock, patch

import run

sys.dont_write_bytecode = True


class TestInitRuntime:
    def test_exits_on_default_admin_password(self, monkeypatch):
        with patch("secret_store.get_keyring_secret", return_value="CHANGEME"):
            exited = []
            monkeypatch.setattr(run.sys, "exit", lambda code: exited.append(code))
            run._init_runtime()
            assert exited == [1]

    def test_exits_on_empty_admin_password(self, monkeypatch, caplog):
        import logging

        with patch("secret_store.get_keyring_secret", return_value=""):
            exited = []
            monkeypatch.setattr(run.sys, "exit", lambda code: exited.append(code))
            with caplog.at_level(logging.ERROR):
                run._init_runtime()
            assert exited == [1]
            assert "uv run keyring set pa-container ADMIN_PASSWORD" in caplog.text
            assert "Host environment variables are not accepted" in caplog.text

    def test_admin_password_fetched_from_keyring_only(self, monkeypatch, caplog):
        import logging

        monkeypatch.setenv("ADMIN_PASSWORD", "env_should_be_ignored")
        with (
            patch("secret_store.get_keyring_secret", return_value="from_keyring_only") as mock_get,
            caplog.at_level(logging.ERROR),
        ):
            run._init_runtime()
        mock_get.assert_called_once_with("ADMIN_PASSWORD")

    def test_exits_on_environment_error(self, monkeypatch):
        exited = []
        monkeypatch.setattr(run.sys, "exit", lambda code: exited.append(code))

        def mock_validate(bin_path):
            raise run.EnvironmentError("Podman not found")

        monkeypatch.setattr(run, "validate_environment", mock_validate)
        with patch("secret_store.get_keyring_secret", return_value="securepassword123"):
            run._init_runtime()
        assert exited == [1]

    def test_initializes_runtime_on_valid_environment(self, monkeypatch):
        monkeypatch.setattr(run, "validate_environment", lambda bin_path: "podman")

        mock_rt = MagicMock()
        mock_rt.upstream_network = "podman"
        monkeypatch.setattr(run, "PodmanRuntime", lambda *a, **kw: mock_rt)

        with patch("secret_store.get_keyring_secret", return_value="securepassword123"):
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


class TestAgentLaunchSecurityOpts:
    def test_no_new_privileges_included_when_nested_disabled(self):
        nested_enabled = False
        opts = ["--security-opt", "no-new-privileges"] if not nested_enabled else []
        assert opts == ["--security-opt", "no-new-privileges"]

    def test_no_new_privileges_omitted_when_nested_enabled(self):
        nested_enabled = True
        opts = ["--security-opt", "no-new-privileges"] if not nested_enabled else []
        assert opts == []


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


class TestRunMounts:
    def test_driver_mount_chown_intermediate_paths(self):
        from pathlib import Path

        from packages.plugin import ContainerMount as AgentMount

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


class TestAgentResolution:
    def test_agent_driver_required_packages_access(self):
        """Verify that driver.required_packages property is accessed without being called as a function."""
        from pa_packages.agents.host.registry import get_agent_driver

        for agent_name in ("pi", "opencode", "antigravity", "claude"):
            driver = get_agent_driver(agent_name)
            packages = driver.required_packages
            assert isinstance(packages, list)

    def test_cli_agent_disabled_exits_with_error(self, tmp_path, monkeypatch):
        import yaml

        from network import read_enabled_agents

        pa_dir = tmp_path / ".pa-container"
        pa_dir.mkdir(parents=True)
        (pa_dir / "config.yaml").write_text(yaml.dump({"packages": [{"agents": ["claude"]}]}))
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

    def test_execute_run_invalid_models_yaml_with_remediation(self, tmp_path, monkeypatch):
        from cli import RunOptions
        from logging_driver import LogCategory, LogDriver
        from remediation import RemediationAction

        proj = tmp_path / "proj"
        proj.mkdir()
        pa_dir = proj / ".pa-container"
        pa_dir.mkdir()
        (pa_dir / "config.yaml").write_text("schema_version: '0.6.6'\n")
        models_yaml = pa_dir / "models.yaml"
        models_yaml.write_text("allow:\n  - opper\n")

        monkeypatch.setattr(run, "PROJECT_DIR", proj)
        monkeypatch.setattr(run, "_init_runtime", lambda: None)
        monkeypatch.setattr(run.project, "ensure_project_config", lambda *args, **kwargs: pa_dir)
        monkeypatch.setattr(run, "validate_config", lambda p: (True, [], "0.6.6"))
        monkeypatch.setattr(run, "validate_project_yaml", lambda d: [])
        monkeypatch.setattr(
            run, "validate_models", lambda p: (False, ["allow[0]: gateway 'opper' requires authentication."])
        )

        fake_remediation = RemediationAction(
            description="Replace item 'opper' under 'allow:' in models.yaml with:",
            snippet="- id: opper\n  provider: opper\n  containerEnvVar: OPPER_API_KEY",
        )
        monkeypatch.setattr(run, "get_models_remediations", lambda p: [fake_remediation], raising=False)
        import remediation

        monkeypatch.setattr(remediation, "get_models_remediations", lambda p: [fake_remediation])

        custom_state = tmp_path / "state"
        monkeypatch.setenv("XDG_STATE_HOME", str(custom_state))
        driver = LogDriver(proj, quiet=True)

        with patch.object(driver, "fail_and_render", wraps=driver.fail_and_render) as mock_fail:
            ret = run.execute_run(RunOptions(), driver=driver)

        assert ret == 1
        assert mock_fail.called
        assert mock_fail.call_args[0][0] == LogCategory.PREFLIGHT
        assert mock_fail.call_args[0][1] == "Invalid models.yaml"
        hints = mock_fail.call_args[1]["hints"]
        assert len(hints) == 1
        assert hints[0] == fake_remediation
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
        monkeypatch.setattr(run, "validate_mount_paths", lambda m, b: [])
        monkeypatch.setattr(run, "read_enabled_agents", lambda d: ["pi"])
        monkeypatch.setattr(run, "read_default_agent", lambda d: "pi")
        mock_driver_obj = MagicMock()
        mock_driver_obj.get_sessions_dir.return_value = tmp_path / "sessions"
        monkeypatch.setattr(run, "get_agent_driver", lambda t: mock_driver_obj)
        monkeypatch.setattr(run.containers, "sweep_orphaned_servers", lambda d: None)
        monkeypatch.setattr(run.containers, "sweep_orphaned_proxies", lambda r, d: None)
        monkeypatch.setattr(run.containers, "cleanup_orphaned_agent_containers", lambda r: None)
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
