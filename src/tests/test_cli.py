from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.dont_write_bytecode = True

from cli import (
    BuildOptions,
    CleanOptions,
    LogsOptions,
    ProxyOptions,
    RunOptions,
    _parse_duration,
    create_parser,
    handle_logs_command,
    handle_proxy_command,
    main,
    parse_cli_args,
)


class TestParseDuration:
    def test_days(self) -> None:
        assert _parse_duration("7d") == 7 * 86400

    def test_hours(self) -> None:
        assert _parse_duration("24h") == 24 * 3600

    def test_minutes(self) -> None:
        assert _parse_duration("30m") == 30 * 60

    def test_seconds(self) -> None:
        assert _parse_duration("45s") == 45.0

    def test_default_days(self) -> None:
        assert _parse_duration("10") == 10 * 86400


class TestCliParser:
    def test_parser_prog_name(self) -> None:
        parser = create_parser()
        assert parser.prog == "pa"

    def test_parser_version_missing_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("cli.get_git_tag_version", lambda r: None)
        with pytest.raises(RuntimeError, match="Unable to determine pa-container version"):
            create_parser()

    def test_zero_arguments_displays_help(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as exc_info:
            parse_cli_args([])
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "usage: pa" in captured.out
        assert "positional arguments:" in captured.out

    def test_missing_subcommand_with_flags_fails(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit):
            parse_cli_args(["--verbose"])
        captured = capsys.readouterr()
        assert "the following arguments are required: <command>" in captured.err

    def test_run_options_parsing(self) -> None:
        cmd, options = parse_cli_args(
            [
                "run",
                "--agent",
                "opencode",
                "--open-browser",
                "--verbose",
                "--log-level",
                "DEBUG",
            ]
        )
        assert cmd == "run"
        assert isinstance(options, RunOptions)
        assert options.agent == "opencode"
        assert options.open_browser is True
        assert options.verbose is True
        assert options.log_level == "DEBUG"

    def test_run_options_with_package_plugin(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        pa_dir = tmp_path / ".pa-container"
        pa_dir.mkdir()
        (pa_dir / "config.yaml").write_text("packages:\n  - t3\n")
        monkeypatch.setattr("cli.PROJECT_DIR", tmp_path)

        cmd, options = parse_cli_args(
            [
                "run",
                "--agent",
                "opencode",
                "--t3",
                "--t3-lan",
                "--t3-port",
                "8080",
                "--t3-advertise-host",
                "192.168.1.10",
                "--t3-tunnel",
                "cloudflare",
                "--t3-tunnel-quick",
            ]
        )
        assert cmd == "run"
        assert isinstance(options, RunOptions)
        assert options.t3 is True
        assert options.t3_lan is True
        assert options.t3_port == "8080"
        assert options.t3_advertise_host == "192.168.1.10"
        assert options.t3_tunnel == "cloudflare"
        assert options.t3_tunnel_quick is True

    def test_unconfigured_package_flag_remediation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr("cli.PROJECT_DIR", tmp_path)
        with pytest.raises(SystemExit) as exc_info:
            parse_cli_args(["run", "--t3"])
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "The '--t3' option requires the 't3' capability package" in captured.err
        assert "packages:\n        - t3" in captured.err

    def test_run_open_browser_flag(self) -> None:
        cmd, options = parse_cli_args(["run", "--open-browser"])
        assert cmd == "run"
        assert isinstance(options, RunOptions)
        assert options.open_browser is True

    def test_run_no_open_browser_flag_fails(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit):
            parse_cli_args(["run", "--no-open-browser"])
        captured = capsys.readouterr()
        assert "unrecognized arguments: --no-open-browser" in captured.err

    def test_posix_passthrough_separator(self) -> None:
        cmd, options = parse_cli_args(
            [
                "run",
                "--agent",
                "pi",
                "--",
                "--help",
                "-c",
                "custom_arg",
            ]
        )
        assert cmd == "run"
        assert isinstance(options, RunOptions)
        assert options.agent == "pi"
        assert options.container_argv == ["--help", "-c", "custom_arg"]

    def test_implicit_run_with_flags_fails(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit):
            parse_cli_args(["--agent", "claude", "--verbose"])
        captured = capsys.readouterr()
        assert "invalid choice: 'claude'" in captured.err

    def test_build_options_parsing(self) -> None:
        cmd, options = parse_cli_args(
            [
                "build",
                "--packages",
                "go,rust",
                "--llama",
                "--llama-backend",
                "metal",
                "--llama-tag",
                "v0.9.0",
                "--no-clean",
                "--no-prune",
                "--clean",
                "--cmake-arg",
                "-DFOO=1",
                "--quiet",
            ]
        )
        assert cmd == "build"
        assert isinstance(options, BuildOptions)
        assert options.packages == "go,rust"
        assert options.llama is True
        assert options.llama_backend == "metal"
        assert options.llama_tag == "v0.9.0"
        assert options.no_clean is True
        assert options.no_prune is True
        assert options.clean is True
        assert options.cmake_args == ["-DFOO=1"]
        assert options.quiet is True

    def test_clean_options_parsing(self) -> None:
        cmd, options = parse_cli_args(["clean", "--all"])
        assert cmd == "clean"
        assert isinstance(options, CleanOptions)
        assert options.all is True
        assert options.logs is True
        assert options.build_cache is True

    def test_logs_options_parsing(self) -> None:
        cmd, options = parse_cli_args(["logs", "--follow", "--category", "build", "--lines", "100"])
        assert cmd == "logs"
        assert isinstance(options, LogsOptions)
        assert options.action == "view"
        assert options.follow is True
        assert options.category == "build"
        assert options.lines == 100

    def test_logs_clean_subcommand_parsing(self) -> None:
        cmd, options = parse_cli_args(["logs", "clean", "--all-projects", "--older-than", "3d", "--force"])
        assert cmd == "logs"
        assert isinstance(options, LogsOptions)
        assert options.action == "clean"
        assert options.all_projects is True
        assert options.older_than == "3d"
        assert options.force is True


class TestHandleLogsCommand:
    def test_logs_path_prints_path(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr("cli.PROJECT_DIR", tmp_path)
        options = LogsOptions(path=True)
        with patch("rich.console.Console.print") as mock_print:
            code = handle_logs_command(options)
            assert code == 0
            assert mock_print.called

    def test_logs_list_empty(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr("cli.PROJECT_DIR", tmp_path)
        options = LogsOptions(list=True)
        with patch("rich.console.Console.print") as mock_print:
            code = handle_logs_command(options)
            assert code == 0
            assert mock_print.called

    def test_logs_list_with_files(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr("cli.PROJECT_DIR", tmp_path)
        from project import get_project_logs_dir

        logs_dir = get_project_logs_dir(tmp_path)
        (logs_dir / "run-20261107-120000.log").write_text("test run log")
        (logs_dir / "build-20261107-120000.log").write_text("test build log")

        options = LogsOptions(list=True)
        with patch("rich.console.Console.print") as mock_print:
            code = handle_logs_command(options)
            assert code == 0
            assert mock_print.called

    def test_logs_clean_project(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr("cli.PROJECT_DIR", tmp_path)
        from project import get_project_logs_dir

        logs_dir = get_project_logs_dir(tmp_path)
        (logs_dir / "run-20261107-120000.log").write_text("content")

        options = LogsOptions(action="clean", force=True)
        with patch("rich.console.Console.print"):
            code = handle_logs_command(options)
            assert code == 0
            assert not (logs_dir / "run-20261107-120000.log").exists()

    def test_logs_view_tail_and_filter(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr("cli.PROJECT_DIR", tmp_path)
        from project import get_project_logs_dir

        logs_dir = get_project_logs_dir(tmp_path)
        run_file = logs_dir / "run-test.log"
        run_file.write_text("[INFO] [build] building layer 1\n[INFO] [proxy] starting proxy\n")
        (logs_dir / "latest.log").symlink_to(run_file.name)

        options = LogsOptions(category="build", lines=10)
        with patch("rich.console.Console.print") as mock_print:
            code = handle_logs_command(options)
            assert code == 0
            mock_print.assert_called_with("[INFO] [build] building layer 1")

    def test_logs_view_build_log(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr("cli.PROJECT_DIR", tmp_path)
        from project import get_project_logs_dir

        logs_dir = get_project_logs_dir(tmp_path)
        build_file = logs_dir / "build-test.log"
        build_file.write_text("[INFO] [build] building test target\n")
        (logs_dir / "latest-build.log").symlink_to(build_file.name)

        options = LogsOptions(build=True, lines=5)
        with patch("rich.console.Console.print") as mock_print:
            code = handle_logs_command(options)
            assert code == 0
            mock_print.assert_called_with("[INFO] [build] building test target")

    def test_logs_view_missing_log_files(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr("cli.PROJECT_DIR", tmp_path)
        options_run = LogsOptions(build=False)
        with patch("rich.console.Console.print") as mock_print:
            code = handle_logs_command(options_run)
            assert code == 0
            mock_print.assert_called_with("[yellow]No run log found for this project.[/yellow]")

        options_build = LogsOptions(build=True)
        with patch("rich.console.Console.print") as mock_print:
            code = handle_logs_command(options_build)
            assert code == 0
            mock_print.assert_called_with("[yellow]No build log found for this project.[/yellow]")

    def test_logs_clean_all_projects(self, monkeypatch) -> None:
        with (
            patch("cli.clean_all_projects_logs", return_value=[Path("/tmp/p1.log")]) as mock_clean,
            patch("rich.console.Console.print") as mock_print,
        ):
            options = LogsOptions(action="clean", all_projects=True, force=False, older_than="24h")
            code = handle_logs_command(options)
            assert code == 0
            mock_clean.assert_called_once_with(older_than_seconds=86400.0)
            assert mock_print.called

    def test_logs_view_oserror(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr("cli.PROJECT_DIR", tmp_path)
        from project import get_project_logs_dir

        logs_dir = get_project_logs_dir(tmp_path)
        run_file = logs_dir / "run-test.log"
        run_file.write_text("dummy")
        (logs_dir / "latest.log").symlink_to(run_file.name)

        options = LogsOptions()
        with (
            patch.object(Path, "read_text", side_effect=OSError("Disk read error")),
            patch("rich.console.Console.print") as mock_print,
        ):
            code = handle_logs_command(options)
            assert code == 1
            assert any("Could not read log file" in str(c) for c in mock_print.call_args_list)

    def test_logs_follow(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr("cli.PROJECT_DIR", tmp_path)
        from project import get_project_logs_dir

        logs_dir = get_project_logs_dir(tmp_path)
        run_file = logs_dir / "run-test.log"
        run_file.write_text("initial")
        (logs_dir / "latest.log").symlink_to(run_file.name)

        options = LogsOptions(follow=True, category="proxy")
        mock_file = MagicMock()
        mock_file.readline.side_effect = [
            "[proxy] stream 1\n",
            "[network] other\n",
            KeyboardInterrupt(),
        ]

        with (
            patch.object(Path, "open") as mock_open,
            patch("rich.console.Console.print") as mock_print,
        ):
            mock_open.return_value.__enter__.return_value = mock_file
            code = handle_logs_command(options)
            assert code == 0
            mock_print.assert_called_once_with("[proxy] stream 1\n", end="")


class TestCliMain:
    def test_main_logs_subcommand(self) -> None:
        with (
            patch("cli.handle_logs_command", return_value=0) as mock_handle,
            patch("sys.exit") as mock_exit,
        ):
            main(["logs", "--path"])
            mock_handle.assert_called_once()
            mock_exit.assert_called_once_with(0)

    def test_main_clean_subcommand(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr("cli.PROJECT_DIR", tmp_path)
        with (
            patch("cli.init_log_driver") as mock_driver,
            patch("cli.clean_project_logs", return_value=[Path("a.log")]) as mock_clean_logs,
            patch("build.run_clean_pass", return_value=0) as mock_clean_pass,
            patch("sys.exit") as mock_exit,
        ):
            mock_driver.return_value.console.print = MagicMock()
            main(["clean", "--all"])
            mock_clean_logs.assert_called_once()
            mock_clean_pass.assert_called_once_with(purge_cache=True)
            mock_exit.assert_called_once_with(0)

    def test_main_build_clean_flag(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr("cli.PROJECT_DIR", tmp_path)
        with (
            patch("cli.init_log_driver"),
            patch("build.run_clean_pass", return_value=0) as mock_clean_pass,
            patch("sys.exit") as mock_exit,
        ):
            main(["build", "--clean"])
            mock_clean_pass.assert_called_once_with(purge_cache=True)
            mock_exit.assert_called_once_with(0)

    def test_main_build_execute(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr("cli.PROJECT_DIR", tmp_path)
        with (
            patch("cli.init_log_driver"),
            patch("build.execute_build", return_value=0) as mock_execute_build,
            patch("sys.exit") as mock_exit,
        ):
            main(["build", "--llama"])
            mock_execute_build.assert_called_once()
            mock_exit.assert_called_once_with(0)

    def test_main_run_execute(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr("cli.PROJECT_DIR", tmp_path)
        with (
            patch("cli.init_log_driver"),
            patch("run.execute_run", return_value=0) as mock_execute_run,
            patch("sys.exit") as mock_exit,
        ):
            main(["run", "--agent", "claude"])
            mock_execute_run.assert_called_once()
            mock_exit.assert_called_once_with(0)

    def test_main_keyboard_interrupt_exits_130(self) -> None:
        with (
            patch("cli.parse_cli_args", side_effect=KeyboardInterrupt),
            patch("sys.exit") as mock_exit,
        ):
            main(["run"])
            mock_exit.assert_called_once_with(130)

    def test_main_unhandled_exception_caught(self, tmp_path: Path, monkeypatch, caplog) -> None:
        import logging

        monkeypatch.setattr("cli.PROJECT_DIR", tmp_path)
        with (
            patch("cli.init_log_driver"),
            patch("run.execute_run", side_effect=RuntimeError("Unexpected disaster")),
            patch("sys.exit") as mock_exit,
            patch("cli.fail_and_render") as mock_fail,
            caplog.at_level(logging.ERROR),
        ):
            main(["run"])
            mock_exit.assert_called_once_with(1)
            assert mock_fail.called
            assert any("Fatal unhandled CLI exception" in r.getMessage() for r in caplog.records)

    def test_main_missing_global_config(self, tmp_path: Path, monkeypatch, caplog) -> None:
        import logging

        monkeypatch.setattr("cli.PROJECT_DIR", tmp_path)
        with (
            patch("global_config.load_global_config", side_effect=FileNotFoundError("Global config missing")),
            patch("sys.exit") as mock_exit,
            patch("cli.render_hard_error") as mock_render,
            caplog.at_level(logging.ERROR),
        ):
            main(["run"])
            mock_exit.assert_called_once_with(1)
            assert mock_render.called
            assert any("Global configuration missing" in r.getMessage() for r in caplog.records)

    def test_main_invalid_global_config(self, tmp_path: Path, monkeypatch, caplog) -> None:
        import logging

        monkeypatch.setattr("cli.PROJECT_DIR", tmp_path)
        with (
            patch("global_config.load_global_config", side_effect=ValueError("Invalid YAML")),
            patch("sys.exit") as mock_exit,
            patch("cli.render_hard_error") as mock_render,
            caplog.at_level(logging.ERROR),
        ):
            main(["run"])
            mock_exit.assert_called_once_with(1)
            assert mock_render.called
            assert any("Global configuration invalid" in r.getMessage() for r in caplog.records)

    def test_main_resolves_project_logging_retention(self, tmp_path: Path, monkeypatch) -> None:
        import yaml

        monkeypatch.setattr("cli.PROJECT_DIR", tmp_path)
        pa_dir = tmp_path / ".pa-container"
        pa_dir.mkdir()
        (pa_dir / "config.yaml").write_text(
            yaml.dump(
                {
                    "agents": {"enabled": ["pi"], "default": "pi"},
                    "logging": {"retention": {"max_days": 3, "max_launches": 2}},
                }
            )
        )
        with (
            patch("cli.init_log_driver") as mock_init_log,
            patch("run.execute_run", return_value=0),
            patch("sys.exit") as mock_exit,
        ):
            main(["run"])
            mock_exit.assert_called_once_with(0)
            mock_init_log.assert_called_once()
            _, kwargs = mock_init_log.call_args
            assert kwargs["max_days"] == 3
            assert kwargs["max_launches"] == 2

    def test_main_falls_back_to_global_logging_retention(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr("cli.PROJECT_DIR", tmp_path)
        with (
            patch("cli.init_log_driver") as mock_init_log,
            patch("run.execute_run", return_value=0),
            patch("sys.exit") as mock_exit,
        ):
            main(["run"])
            mock_exit.assert_called_once_with(0)
            mock_init_log.assert_called_once()
            _, kwargs = mock_init_log.call_args
            assert kwargs["max_days"] == 14
            assert kwargs["max_launches"] == 10


class TestProxyCli:
    def test_proxy_options_parsing(self) -> None:
        cmd, options = parse_cli_args(["proxy", "--all", "--open", "--url", "--json"])
        assert cmd == "proxy"
        assert isinstance(options, ProxyOptions)
        assert options.all is True
        assert options.open is True
        assert options.url is True
        assert options.json is True

    def test_proxies_alias_fails(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit):
            parse_cli_args(["proxies", "--all"])
        captured = capsys.readouterr()
        assert "invalid choice: 'proxies'" in captured.err

    def test_proxy_active_project(self, tmp_path: Path, monkeypatch) -> None:
        from network import ActiveProxyInfo

        monkeypatch.setattr("cli.PROJECT_DIR", tmp_path)
        (tmp_path / ".pa-container").mkdir()
        fake_proxy = ActiveProxyInfo(
            project_name="test-project",
            project_path=tmp_path,
            project_hash="1234567890",
            container_name="pa-container-proxy-1234567890",
            mitmweb_port=49152,
            mitmweb_url="http://127.0.0.1:49152",
            is_healthy=True,
            active_clients=1,
        )
        with (
            patch("network.get_project_proxy", return_value=fake_proxy),
            patch("rich.console.Console.print") as mock_print,
        ):
            code = handle_proxy_command(ProxyOptions())
            assert code == 0
            output = "".join(str(call) for call in mock_print.call_args_list)
            assert "test-project" in output
            assert "49152" in output

    def test_proxy_inactive_project(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr("cli.PROJECT_DIR", tmp_path)
        (tmp_path / ".pa-container").mkdir()
        with (
            patch("network.get_project_proxy", return_value=None),
            patch("rich.console.Console.print") as mock_print,
        ):
            code = handle_proxy_command(ProxyOptions())
            assert code == 1
            output = "".join(str(call) for call in mock_print.call_args_list)
            assert "No active proxy container running" in output

    def test_proxy_url_flag(self, tmp_path: Path, monkeypatch) -> None:
        from network import ActiveProxyInfo

        monkeypatch.setattr("cli.PROJECT_DIR", tmp_path)
        (tmp_path / ".pa-container").mkdir()
        fake_proxy = ActiveProxyInfo(
            project_name="test-project",
            project_path=tmp_path,
            project_hash="1234567890",
            container_name="pa-container-proxy-1234567890",
            mitmweb_port=49152,
            mitmweb_url="http://127.0.0.1:49152",
            is_healthy=True,
            active_clients=1,
        )
        with (
            patch("network.get_project_proxy", return_value=fake_proxy),
            patch("rich.console.Console.print") as mock_print,
        ):
            code = handle_proxy_command(ProxyOptions(url=True))
            assert code == 0
            mock_print.assert_called_once_with("http://127.0.0.1:49152")

    def test_proxy_json_flag(self, tmp_path: Path, monkeypatch) -> None:
        import json

        from network import ActiveProxyInfo

        monkeypatch.setattr("cli.PROJECT_DIR", tmp_path)
        (tmp_path / ".pa-container").mkdir()
        fake_proxy = ActiveProxyInfo(
            project_name="test-project",
            project_path=tmp_path,
            project_hash="1234567890",
            container_name="pa-container-proxy-1234567890",
            mitmweb_port=49152,
            mitmweb_url="http://127.0.0.1:49152",
            is_healthy=True,
            active_clients=1,
        )
        with (
            patch("network.get_project_proxy", return_value=fake_proxy),
            patch("rich.console.Console.print") as mock_print,
        ):
            code = handle_proxy_command(ProxyOptions(json=True))
            assert code == 0
            printed_raw = mock_print.call_args[0][0]
            data = json.loads(printed_raw)
            assert data["status"] == "running"
            assert data["mitmweb_port"] == 49152

    def test_proxy_open_flag(self, tmp_path: Path, monkeypatch) -> None:
        from network import ActiveProxyInfo

        monkeypatch.setattr("cli.PROJECT_DIR", tmp_path)
        (tmp_path / ".pa-container").mkdir()
        fake_proxy = ActiveProxyInfo(
            project_name="test-project",
            project_path=tmp_path,
            project_hash="1234567890",
            container_name="pa-container-proxy-1234567890",
            mitmweb_port=49152,
            mitmweb_url="http://127.0.0.1:49152",
            is_healthy=True,
            active_clients=1,
        )
        with (
            patch("network.get_project_proxy", return_value=fake_proxy),
            patch("webbrowser.open") as mock_open,
            patch("rich.console.Console.print"),
        ):
            code = handle_proxy_command(ProxyOptions(open=True))
            assert code == 0
            mock_open.assert_called_once_with("http://127.0.0.1:49152")

    def test_proxy_all_empty(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr("cli.PROJECT_DIR", tmp_path)
        with (
            patch("network.list_active_proxies", return_value=[]),
            patch("rich.console.Console.print") as mock_print,
        ):
            code = handle_proxy_command(ProxyOptions(all=True))
            assert code == 0
            mock_print.assert_called_once_with("[dim]No active pa-container proxies found on this system.[/dim]")

    def test_proxy_all_with_proxies(self, tmp_path: Path, monkeypatch) -> None:
        from network import ActiveProxyInfo

        monkeypatch.setattr("cli.PROJECT_DIR", tmp_path)
        proxies = [
            ActiveProxyInfo(
                project_name="p1",
                project_path=Path("/tmp/p1"),
                project_hash="1111111111",
                container_name="pa-container-proxy-1111111111",
                mitmweb_port=50001,
                mitmweb_url="http://127.0.0.1:50001",
                is_healthy=True,
                active_clients=1,
            ),
            ActiveProxyInfo(
                project_name="p2",
                project_path=Path("/tmp/p2"),
                project_hash="2222222222",
                container_name="pa-container-proxy-2222222222",
                mitmweb_port=50002,
                mitmweb_url="http://127.0.0.1:50002",
                is_healthy=False,
                active_clients=0,
            ),
        ]
        with (
            patch("network.list_active_proxies", return_value=proxies),
            patch("rich.console.Console.print") as mock_print,
        ):
            code = handle_proxy_command(ProxyOptions(all=True))
            assert code == 0
            assert mock_print.called

    def test_main_proxy_dispatches(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr("cli.PROJECT_DIR", tmp_path)
        with (
            patch("cli.handle_proxy_command", return_value=0) as mock_handle,
            patch("sys.exit") as mock_exit,
        ):
            main(["proxy", "--all"])
            mock_handle.assert_called_once()
            mock_exit.assert_called_once_with(0)


class TestDynamicPackageCommands:
    def test_main_package_subcommand_dispatches(self, tmp_path: Path, monkeypatch) -> None:
        from packages.loader import get_package_host_module

        desktop_mod = get_package_host_module("virtual-desktop", "desktop")
        monkeypatch.setattr("cli.PROJECT_DIR", tmp_path)
        with (
            patch.object(desktop_mod, "handle_desktop_command", return_value=0) as mock_handle,
            patch("sys.exit") as mock_exit,
        ):
            main(["desktop", "--all"])
            mock_handle.assert_called_once()
            mock_exit.assert_called_once_with(0)
