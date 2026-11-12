from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest
from rich.console import Console

if TYPE_CHECKING:
    from pathlib import Path

sys.dont_write_bytecode = True

from logging_driver import (
    CategoryLogger,
    LogCategory,
    LogDriver,
    Stage,
    StageStatus,
    TaggedFileFormatter,
    clean_all_projects_logs,
    clean_project_logs,
    get_category_logger,
    get_log_driver,
    init_log_driver,
    prune_project_logs,
)


class TestStage:
    def test_render_states(self) -> None:
        # Active without detail
        st = Stage(LogCategory.BUILD, "Building image")
        txt = st.render()
        assert "[build]" in txt.plain
        assert "Building image" in txt.plain

        # Active with detail
        st.detail = "STEP 1/3"
        txt = st.render()
        assert "[build]" in txt.plain
        assert "Building image: STEP 1/3" in txt.plain

        # Completed with detail
        st.complete("cached")
        txt = st.render()
        assert "✔" in txt.plain
        assert "[build]" in txt.plain
        assert "cached" in txt.plain

        # Completed without detail
        st.detail = ""
        txt = st.render()
        assert "✔" in txt.plain
        assert "[build]" in txt.plain

        # Failed with detail
        st.fail("out of memory")
        txt = st.render()
        assert "✗" in txt.plain
        assert "[build]" in txt.plain
        assert "out of memory" in txt.plain


class TestLogCategory:
    def test_enum_values(self) -> None:
        assert LogCategory.PREFLIGHT == "preflight"
        assert LogCategory.BUILD == "build"
        assert LogCategory.PROXY == "proxy"
        assert LogCategory.SERVER == "server"
        assert LogCategory.NETWORK == "network"
        assert LogCategory.AGENT == "agent"


class TestCategoryLogger:
    def test_injects_category(self, caplog: pytest.LogCaptureFixture) -> None:
        logger = get_category_logger("test.cat", LogCategory.PROXY)
        assert isinstance(logger, CategoryLogger)
        assert logger.category == "proxy"

        with caplog.at_level(logging.INFO):
            logger.info("Test proxy message")

        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert getattr(record, "category", None) == "proxy"

    def test_preserves_custom_extra(self, caplog: pytest.LogCaptureFixture) -> None:
        logger = get_category_logger("test.extra", LogCategory.BUILD)
        with caplog.at_level(logging.INFO):
            logger.info("Test message", extra={"custom_field": "val123"})

        record = caplog.records[0]
        assert getattr(record, "category", None) == "build"
        assert getattr(record, "custom_field", None) == "val123"


class TestTaggedFileFormatter:
    def test_formatter_includes_category(self) -> None:
        fmt = TaggedFileFormatter(fmt="[%(levelname)s] [%(category)s] %(message)s")
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=10,
            msg="hello world",
            args=(),
            exc_info=None,
        )
        record.category = "network"  # type: ignore[attr-defined]
        output = fmt.format(record)
        assert "[INFO] [network] hello world" in output

    def test_formatter_defaults_missing_category_to_system(self) -> None:
        fmt = TaggedFileFormatter(fmt="[%(category)s] %(message)s")
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=10,
            msg="plain record",
            args=(),
            exc_info=None,
        )
        output = fmt.format(record)
        assert "[system] plain record" in output


class TestLogDriver:
    def test_initialization_creates_files_and_symlinks(self, tmp_path: Path, monkeypatch) -> None:
        custom_state = tmp_path / "state"
        monkeypatch.setenv("XDG_STATE_HOME", str(custom_state))

        driver = LogDriver(tmp_path, log_level="DEBUG", quiet=True)
        assert driver.session_log_path.exists()
        assert driver.build_log_path.exists()

        latest_run = driver.logs_dir / "latest.log"
        assert latest_run.is_symlink()
        assert latest_run.resolve() == driver.session_log_path.resolve()

        latest_build = driver.logs_dir / "latest-build.log"
        assert latest_build.is_symlink()
        assert latest_build.resolve() == driver.build_log_path.resolve()

        driver.shutdown()

    def test_stage_progression(self, tmp_path: Path, monkeypatch) -> None:
        custom_state = tmp_path / "state"
        monkeypatch.setenv("XDG_STATE_HOME", str(custom_state))

        driver = LogDriver(tmp_path, log_level="INFO", quiet=True)
        driver.start_stage(LogCategory.BUILD, "Compiling toolchain")
        assert driver.active_stage is not None
        assert driver.active_stage.label == "Compiling toolchain"
        assert driver.active_stage.completed is False
        assert driver.active_stage.failed is False

        driver.update_stage("STEP 2/5")
        assert driver.active_stage.detail == "STEP 2/5"

        driver.complete_stage("compiled")
        assert len(driver.stages) == 1
        assert driver.stages[0].completed is True
        assert driver.stages[0].detail == "compiled"
        assert driver.active_stage is None

        driver.start_stage(LogCategory.NETWORK, "Starting proxy")
        driver.fail_stage("port collision")
        assert len(driver.stages) == 2
        assert driver.stages[1].failed is True
        assert driver.stages[1].detail == "port collision"

        # Context manager stage
        with driver.stage(LogCategory.SERVER, "Serving requests") as ctx_st:
            assert driver.active_stage is ctx_st
            assert ctx_st.status == StageStatus.RUNNING

        assert len(driver.stages) == 3
        assert driver.stages[2].completed is True
        assert driver.active_stage is None

        driver.shutdown()

    def test_pause_and_resume_interactive(self, tmp_path: Path, monkeypatch) -> None:
        custom_state = tmp_path / "state"
        monkeypatch.setenv("XDG_STATE_HOME", str(custom_state))

        driver = LogDriver(tmp_path, quiet=False)
        driver._live = MagicMock()
        driver.pause_for_interactive()
        assert driver._interactive_paused is True
        assert driver._live is None

        driver.resume_after_interactive()
        assert driver._interactive_paused is False
        driver.shutdown()

    def test_render_hard_error(self, tmp_path: Path, monkeypatch) -> None:
        custom_state = tmp_path / "state"
        monkeypatch.setenv("XDG_STATE_HOME", str(custom_state))

        driver = LogDriver(tmp_path, quiet=True)
        driver.start_stage(LogCategory.PREFLIGHT, "Validating configuration")
        assert driver.active_stage is not None
        assert driver.active_stage.completed is False
        assert driver.active_stage.failed is False

        with patch.object(driver.console, "print") as mock_print:
            driver.render_hard_error(
                LogCategory.PREFLIGHT,
                "Config Failure",
                "Invalid yaml structure",
                hints=["Fix indentation"],
            )
            assert mock_print.called

        # In-flight step must be marked failed
        assert driver.stages[-1].failed is True
        assert driver.stages[-1].detail == "Invalid yaml structure"
        driver.shutdown()

    def test_render_hard_error_with_remediation_action(self, tmp_path: Path, monkeypatch) -> None:
        from remediation import RemediationAction

        custom_state = tmp_path / "state"
        monkeypatch.setenv("XDG_STATE_HOME", str(custom_state))

        driver = LogDriver(tmp_path, quiet=True)
        driver.start_stage(LogCategory.PREFLIGHT, "Validating models")

        action = RemediationAction(
            description="Replace item in models.yaml with:",
            snippet="- id: opper\n  provider: opper",
            companion_commands=("uv run keyring set pa-container OPPER_API_KEY",),
        )

        with patch.object(driver.console, "print") as mock_print:
            driver.render_hard_error(
                LogCategory.PREFLIGHT,
                "Invalid models.yaml",
                "allow[3]: gateway 'opper' requires authentication.",
                hints=[action],
            )
            assert mock_print.called

        assert driver.stages[-1].failed is True
        driver.shutdown()

    def test_fail_and_render(self, tmp_path: Path, monkeypatch, caplog: pytest.LogCaptureFixture) -> None:
        custom_state = tmp_path / "state"
        monkeypatch.setenv("XDG_STATE_HOME", str(custom_state))

        driver = LogDriver(tmp_path, quiet=True)
        driver.start_stage(LogCategory.PREFLIGHT, "Checking setup")

        test_logger = get_category_logger("test.source", LogCategory.PREFLIGHT)
        with patch.object(driver.console, "print") as mock_print, caplog.at_level(logging.ERROR):
            driver.fail_and_render(
                LogCategory.PREFLIGHT,
                "Fatal Setup Error",
                "Something went wrong",
                hints=["Check prerequisites"],
                source_logger=test_logger,
            )
            assert mock_print.called

        assert driver.stages[-1].failed is True
        assert driver.stages[-1].detail == "Something went wrong"

        # Check that error record was emitted with category
        error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert len(error_records) >= 1
        assert any(getattr(r, "category", None) == "preflight" for r in error_records)
        assert any("Fatal Setup Error: Something went wrong" in r.getMessage() for r in error_records)

        driver.shutdown()

    def test_run_command_logged_success(self, tmp_path: Path, monkeypatch) -> None:
        custom_state = tmp_path / "state"
        monkeypatch.setenv("XDG_STATE_HOME", str(custom_state))

        driver = LogDriver(tmp_path, quiet=True)
        result = driver.run_command_logged(
            [sys.executable, "-c", "print('hello from subprocess')"],
            category=LogCategory.BUILD,
            label="test python echo",
        )
        assert result.returncode == 0
        assert "hello from subprocess" in result.stdout

        driver.shutdown()

        # Verify output was written to session log
        content = driver.session_log_path.read_text(encoding="utf-8")
        assert "hello from subprocess" in content

    def test_run_command_logged_failure(self, tmp_path: Path, monkeypatch) -> None:
        custom_state = tmp_path / "state"
        monkeypatch.setenv("XDG_STATE_HOME", str(custom_state))

        driver = LogDriver(tmp_path, quiet=True)
        with pytest.raises(subprocess.CalledProcessError):
            driver.run_command_logged(
                [sys.executable, "-c", "import sys; sys.exit(42)"],
                category=LogCategory.BUILD,
                label="failing test cmd",
                check=True,
            )

        driver.shutdown()


class TestRetentionAndCleaning:
    def test_prune_project_logs_by_count(self, tmp_path: Path) -> None:
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()

        # Create 15 run logs with staggered mtimes
        now = time.time()
        for i in range(15):
            f = logs_dir / f"run-20261107-{i:02d}0000.log"
            f.write_text(f"run {i}")
            os.utime(f, (now - (15 - i) * 10, now - (15 - i) * 10))

        pruned = prune_project_logs(logs_dir, max_launches=5, max_days=None)
        assert pruned == 10
        remaining = [f for f in logs_dir.iterdir() if f.name.startswith("run-")]
        assert len(remaining) == 5

    def test_prune_project_logs_by_age(self, tmp_path: Path) -> None:
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()

        now = time.time()
        old_file = logs_dir / "run-old.log"
        old_file.write_text("old")
        os.utime(old_file, (now - 20 * 86400, now - 20 * 86400))

        recent_file = logs_dir / "run-new.log"
        recent_file.write_text("new")
        os.utime(recent_file, (now - 1 * 86400, now - 1 * 86400))

        pruned = prune_project_logs(logs_dir, max_days=14, max_launches=None)
        assert pruned == 1
        assert not old_file.exists()
        assert recent_file.exists()

    def test_clean_project_logs(self, tmp_path: Path, monkeypatch) -> None:
        custom_state = tmp_path / "state"
        monkeypatch.setenv("XDG_STATE_HOME", str(custom_state))

        project_dir = tmp_path / "workspace"
        project_dir.mkdir()
        from project import get_project_logs_dir

        logs_dir = get_project_logs_dir(project_dir)
        (logs_dir / "run-1.log").write_text("run1")
        (logs_dir / "build-1.log").write_text("build1")
        (logs_dir / "latest.log").symlink_to("run-1.log")

        deleted = clean_project_logs(project_dir)
        assert len(deleted) == 2
        assert not (logs_dir / "run-1.log").exists()
        assert not (logs_dir / "build-1.log").exists()

    def test_clean_all_projects_logs(self, tmp_path: Path, monkeypatch) -> None:
        custom_state = tmp_path / "state"
        monkeypatch.setenv("XDG_STATE_HOME", str(custom_state))

        p1 = tmp_path / "p1"
        p2 = tmp_path / "p2"
        p1.mkdir()
        p2.mkdir()
        from project import get_project_logs_dir

        l1 = get_project_logs_dir(p1)
        l2 = get_project_logs_dir(p2)
        (l1 / "run-p1.log").write_text("p1")
        (l2 / "run-p2.log").write_text("p2")

        deleted = clean_all_projects_logs()
        assert len(deleted) == 2
        assert not (l1 / "run-p1.log").exists()
        assert not (l2 / "run-p2.log").exists()

    def test_singleton_init_and_get(self, tmp_path: Path, monkeypatch) -> None:
        custom_state = tmp_path / "state"
        monkeypatch.setenv("XDG_STATE_HOME", str(custom_state))

        drv = init_log_driver(tmp_path, quiet=True)
        assert get_log_driver() is drv
        drv.shutdown()

    def test_custom_log_file(self, tmp_path: Path, monkeypatch) -> None:
        custom_state = tmp_path / "state"
        monkeypatch.setenv("XDG_STATE_HOME", str(custom_state))

        custom_file = tmp_path / "custom" / "my-session.log"
        driver = LogDriver(tmp_path, log_file=custom_file, quiet=True)
        assert driver.session_log_path == custom_file.resolve()
        assert custom_file.exists()
        driver.shutdown()

    def test_verbose_and_non_terminal_stages(self, tmp_path: Path, monkeypatch) -> None:
        custom_state = tmp_path / "state"
        monkeypatch.setenv("XDG_STATE_HOME", str(custom_state))

        from rich.console import Console

        # Verbose
        driver = LogDriver(tmp_path, verbose=True)
        with patch.object(driver.console, "print") as mock_print:
            driver.start_stage(LogCategory.BUILD, "compiling")
            driver.update_stage("50%")
            driver.complete_stage("finished")
            driver.start_stage(LogCategory.SERVER, "starting")
            driver.fail_stage("failed")
            assert mock_print.call_count >= 5
        driver.shutdown()

        # Non-terminal, non-quiet
        driver2 = LogDriver(tmp_path, quiet=False, verbose=False)
        driver2.console = Console(force_terminal=False)
        with patch.object(driver2.console, "print") as mock_print2:
            driver2.start_stage(LogCategory.BUILD, "compiling non-term")
            driver2.complete_stage()
            driver2.start_stage(LogCategory.SERVER, "starting non-term")
            driver2.fail_stage("error non-term")
            assert mock_print2.call_count >= 4
        driver2.shutdown()

    def test_live_rendering(self, tmp_path: Path, monkeypatch) -> None:
        custom_state = tmp_path / "state"
        monkeypatch.setenv("XDG_STATE_HOME", str(custom_state))

        from rich.console import Console

        driver = LogDriver(tmp_path, quiet=False, verbose=False)
        driver.console = Console(force_terminal=True)
        with patch("logging_driver.Live") as mock_live_cls:
            mock_live_inst = MagicMock()
            mock_live_cls.return_value = mock_live_inst

            driver.start_stage(LogCategory.NETWORK, "configuring")
            mock_live_cls.assert_called_once()
            assert "get_renderable" in mock_live_cls.call_args[1]
            mock_live_inst.start.assert_called_once()

            driver.update_stage("subnet ready")
            mock_live_inst.refresh.assert_called()

            driver.complete_stage()
            mock_live_inst.refresh.assert_called()

            driver.start_stage(LogCategory.BUILD, "compile")
            driver.fail_stage("error")
            mock_live_inst.refresh.assert_called()

        driver.shutdown()

    def test_run_command_logged_step_regex_and_nocheck(self, tmp_path: Path, monkeypatch) -> None:
        custom_state = tmp_path / "state"
        monkeypatch.setenv("XDG_STATE_HOME", str(custom_state))

        driver = LogDriver(tmp_path, verbose=True)
        script = "print('STEP 1/2: Preparing build'); print('STEP 2/2: Finishing'); import sys; sys.exit(7)"
        res = driver.run_command_logged(
            [sys.executable, "-c", script],
            category=LogCategory.BUILD,
            label="multistep build",
            check=False,
        )
        assert res.returncode == 7
        assert "STEP 1/2" in res.stdout
        assert driver.stages[-1].failed is True
        driver.shutdown()

    def test_run_command_logged_output_streaming_updates_detail(self, tmp_path: Path, monkeypatch) -> None:
        custom_state = tmp_path / "state"
        monkeypatch.setenv("XDG_STATE_HOME", str(custom_state))

        driver = LogDriver(tmp_path, verbose=False)
        st = driver.start_stage(LogCategory.BUILD, "compile task")

        updates: list[str] = []
        original_update = driver.update_stage

        def tracking_update(detail: str) -> None:
            updates.append(detail)
            original_update(detail)

        monkeypatch.setattr(driver, "update_stage", tracking_update)

        script = (
            "import sys\n"
            "print('\\x1b[32mCompiling foo.c\\x1b[0m', flush=True)\n"
            "print('Progress 50%\\rProgress 100%', flush=True)\n"
        )
        res = driver.run_command_logged(
            [sys.executable, "-c", script],
            category=LogCategory.BUILD,
            label="compiler",
        )
        assert res.returncode == 0
        assert "Compiling foo.c" in updates
        assert "Progress 100%" in updates
        driver.complete_stage()
        assert st.completed is True
        assert st.detail == ""  # detail is cleared on completion
        driver.shutdown()

    def test_render_stages_line_truncation(self, tmp_path: Path, monkeypatch) -> None:
        import io

        custom_state = tmp_path / "state"
        monkeypatch.setenv("XDG_STATE_HOME", str(custom_state))

        driver = LogDriver(tmp_path)
        driver.console = Console(file=io.StringIO(), width=50, no_color=True)
        st = driver.start_stage(LogCategory.BUILD, "short label")
        st.update("a" * 100)

        rendered = driver._render_stages().plain
        line = rendered.splitlines()[0]
        assert len(line) <= 50
        assert line.endswith("…")
        driver.shutdown()

    def test_prune_and_clean_edge_cases(self, tmp_path: Path, monkeypatch) -> None:
        custom_state = tmp_path / "state"
        monkeypatch.setenv("XDG_STATE_HOME", str(custom_state))

        # Missing dir returns 0
        missing = tmp_path / "nonexistent"
        assert prune_project_logs(missing) == 0
        assert clean_project_logs(missing) == []

        # clean_all_projects_logs when empty
        monkeypatch.setenv("XDG_STATE_HOME", str(missing))
        assert clean_all_projects_logs() == []

        # clean with older_than_seconds
        state_dir = tmp_path / "state_test"
        monkeypatch.setenv("XDG_STATE_HOME", str(state_dir))
        p1 = tmp_path / "p1"
        p1.mkdir(parents=True)
        from project import get_project_logs_dir

        logs_dir = get_project_logs_dir(p1)
        recent_log = logs_dir / "run-recent.log"
        recent_log.write_text("recent")
        old_log = logs_dir / "run-old.log"
        old_log.write_text("old")
        now = time.time()
        os.utime(old_log, (now - 3600, now - 3600))

        # Delete older than 1800s
        del_p = clean_project_logs(p1, older_than_seconds=1800)
        assert len(del_p) == 1
        assert not old_log.exists()
        assert recent_log.exists()

        # Delete all projects older than 1800s
        p2 = tmp_path / "p2"
        p2.mkdir(parents=True)
        logs_dir2 = get_project_logs_dir(p2)
        old_log2 = logs_dir2 / "run-old2.log"
        old_log2.write_text("old2")
        os.utime(old_log2, (now - 3600, now - 3600))

        del_all = clean_all_projects_logs(older_than_seconds=1800)
        assert len(del_all) == 1
        assert not old_log2.exists()

        # prune_expired_logs on driver
        driver = LogDriver(p1, quiet=True, max_days=1, max_launches=1)
        driver.prune_expired_logs()
        driver.shutdown()


class TestConsoleLogHandlerRouting:
    def test_logger_events_route_to_active_stage_detail(self, tmp_path: Path, monkeypatch) -> None:
        custom_state = tmp_path / "state"
        monkeypatch.setenv("XDG_STATE_HOME", str(custom_state))

        driver = LogDriver(tmp_path, quiet=False, verbose=False)
        driver.start_stage(LogCategory.SERVER, "Starting llama-server")
        assert driver.active_stage is not None
        assert driver.active_stage.detail == ""

        # Emitting logger.info on server category logger routes into active stage detail
        srv_logger = get_category_logger("test.server", LogCategory.SERVER)
        srv_logger.info("Allocated port 58210")

        assert driver.active_stage.detail == "Allocated port 58210"
        driver.shutdown()

    def test_logger_warning_and_error_handling(self, tmp_path: Path, monkeypatch) -> None:
        custom_state = tmp_path / "state"
        monkeypatch.setenv("XDG_STATE_HOME", str(custom_state))

        driver = LogDriver(tmp_path, quiet=False, verbose=False)
        driver.start_stage(LogCategory.PROXY, "Starting proxy")

        with patch.object(driver, "_print") as mock_print:
            proxy_logger = get_category_logger("test.proxy", LogCategory.PROXY)
            proxy_logger.warning("Certificate expires soon")
            mock_print.assert_called_once()
            assert "Certificate expires soon" in str(mock_print.call_args)

        proxy_logger.error("Port 8080 collision")
        assert driver.stages[-1].failed is True
        assert driver.stages[-1].detail == "Port 8080 collision"

        driver.shutdown()

    def test_logger_verbose_streams_all_levels(self, tmp_path: Path, monkeypatch) -> None:
        custom_state = tmp_path / "state"
        monkeypatch.setenv("XDG_STATE_HOME", str(custom_state))

        driver = LogDriver(tmp_path, log_level="DEBUG", verbose=True)
        with patch.object(driver.console, "print") as mock_print:
            bld_logger = get_category_logger("test.build", LogCategory.BUILD)
            bld_logger.debug("CMake flag: -DFOO=1")
            bld_logger.info("Building target")
            bld_logger.warning("Unused variable")
            bld_logger.error("Compilation error")
            assert mock_print.call_count == 4

        driver.shutdown()

    def test_logger_quiet_filters_non_errors(self, tmp_path: Path, monkeypatch) -> None:
        custom_state = tmp_path / "state"
        monkeypatch.setenv("XDG_STATE_HOME", str(custom_state))

        driver = LogDriver(tmp_path, quiet=True)
        with patch.object(driver, "_print") as mock_print:
            net_logger = get_category_logger("test.net", LogCategory.NETWORK)
            net_logger.info("Normal network event")
            net_logger.warning("Network warning")
            assert mock_print.call_count == 0

            net_logger.error("Network bridge failure")
            assert mock_print.call_count == 1
            assert "Network bridge failure" in str(mock_print.call_args)

        driver.shutdown()

    def test_logger_interactive_paused_suppressed(self, tmp_path: Path, monkeypatch) -> None:
        custom_state = tmp_path / "state"
        monkeypatch.setenv("XDG_STATE_HOME", str(custom_state))

        driver = LogDriver(tmp_path, verbose=True)
        driver.pause_for_interactive()

        with patch.object(driver.console, "print") as mock_print:
            agent_logger = get_category_logger("test.agent", LogCategory.AGENT)
            agent_logger.info("Event during container session")
            assert mock_print.call_count == 0

        driver.shutdown()
