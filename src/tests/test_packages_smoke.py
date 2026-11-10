from __future__ import annotations

import os
import shutil
import subprocess
import sys
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

sys.dont_write_bytecode = True

if TYPE_CHECKING:
    from pathlib import Path

from packages import (
    PackageVerificationResult,
    discover_packages,
    render_verification_results,
    verify_package,
    verify_package_integration,
    verify_packages,
    verify_packages_integration,
)


def test_all_packages_have_verification_contracts():
    """Verify that every single package in packages/ defines a verification contract."""
    pkgs = discover_packages()
    assert len(pkgs) >= 20

    missing_commands = []
    for name, p in pkgs.items():
        if not p.verification.command.strip():
            missing_commands.append(name)

    assert not missing_commands, f"Packages missing verification commands: {missing_commands}"


def test_verify_package_missing_manifest(tmp_path: Path):
    res = verify_package("non-existent-pkg-xyz", repo_root=tmp_path)
    assert res.passed is False
    assert "Manifest not found" in (res.error or "")


def test_verify_package_no_command(tmp_path: Path):
    pkg_dir = tmp_path / "packages" / "no-cmd"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "package.yaml").write_text("name: no-cmd\nversion: 1.0.0\n")

    res = verify_package("no-cmd", repo_root=tmp_path)
    assert res.passed is True
    assert "skipped" in res.output


def test_verify_package_success_mocked(tmp_path: Path):
    pkg_dir = tmp_path / "packages" / "mock-tool"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "package.yaml").write_text(
        "name: mock-tool\n"
        "version: 1.0.0\n"
        "runtime:\n"
        "  dependencies:\n"
        "    - node\n"
        "verification:\n"
        "    command: mock --version\n"
        "    expected_output_contains: 'mock 1.0.0'\n"
    )

    with (
        patch("packages.verification.ensure_base_image"),
        patch("packages.verification.ensure_package_images"),
        patch("subprocess.run") as mock_run,
    ):
        # 1st run: build ephemeral container
        build_mock = MagicMock(returncode=0, stdout="Successfully built")
        # 2nd run: execute verification command
        exec_mock = MagicMock(returncode=0, stdout="mock 1.0.0 (x86_64)")
        # 3rd run: rmi cleanup
        cleanup_mock = MagicMock(returncode=0)

        mock_run.side_effect = [build_mock, exec_mock, cleanup_mock]

        res = verify_package("mock-tool", repo_root=tmp_path)
        assert res.passed is True
        assert res.error is None
        assert "mock 1.0.0" in res.output


def test_verify_package_exit_code_failure_mocked(tmp_path: Path):
    pkg_dir = tmp_path / "packages" / "fail-tool"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "package.yaml").write_text(
        "name: fail-tool\nversion: 1.0.0\nverification:\n    command: fail --version\n"
    )

    with (
        patch("packages.verification.ensure_base_image"),
        patch("packages.verification.ensure_package_images"),
        patch("subprocess.run") as mock_run,
    ):
        build_mock = MagicMock(returncode=0, stdout="Successfully built")
        exec_mock = MagicMock(returncode=127, stdout="sh: fail: command not found")
        cleanup_mock = MagicMock(returncode=0)

        mock_run.side_effect = [build_mock, exec_mock, cleanup_mock]

        res = verify_package("fail-tool", repo_root=tmp_path)
        assert res.passed is False
        assert "exit code 127" in (res.error or "")


def test_verify_package_output_mismatch_mocked(tmp_path: Path):
    pkg_dir = tmp_path / "packages" / "mismatch-tool"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "package.yaml").write_text(
        "name: mismatch-tool\n"
        "version: 1.0.0\n"
        "verification:\n"
        "    command: echo unexpected\n"
        "    expected_output_contains: 'expected-token'\n"
    )

    with (
        patch("packages.verification.ensure_base_image"),
        patch("packages.verification.ensure_package_images"),
        patch("subprocess.run") as mock_run,
    ):
        build_mock = MagicMock(returncode=0, stdout="Successfully built")
        exec_mock = MagicMock(returncode=0, stdout="unexpected")
        cleanup_mock = MagicMock(returncode=0)

        mock_run.side_effect = [build_mock, exec_mock, cleanup_mock]

        res = verify_package("mismatch-tool", repo_root=tmp_path)
        assert res.passed is False
        assert "Expected substring 'expected-token' not found" in (res.error or "")


def test_verify_package_timeout_mocked(tmp_path: Path):
    pkg_dir = tmp_path / "packages" / "slow-tool"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "package.yaml").write_text("name: slow-tool\nversion: 1.0.0\nverification:\n    command: sleep 100\n")

    with (
        patch("packages.verification.ensure_base_image"),
        patch("packages.verification.ensure_package_images"),
        patch("subprocess.run") as mock_run,
    ):
        build_mock = MagicMock(returncode=0, stdout="Successfully built")
        mock_run.side_effect = [
            build_mock,
            subprocess.TimeoutExpired(cmd="run", timeout=1),
            MagicMock(returncode=0),
        ]

        res = verify_package("slow-tool", repo_root=tmp_path, timeout_seconds=1)
        assert res.passed is False
        assert "timed out after 1s" in (res.error or "")


def test_render_verification_results():
    results = [
        PackageVerificationResult(
            package="p1",
            command="p1 --version",
            passed=True,
            duration_ms=120.0,
            output="v1.0.0",
        ),
        PackageVerificationResult(
            package="p2",
            command="p2 --version",
            passed=False,
            duration_ms=300.0,
            output="",
            error="Exit code 1",
        ),
    ]
    # Should execute without throwing exceptions
    render_verification_results(results)


def test_ensure_base_image_already_exists():
    with patch("subprocess.run") as mock_run, patch("build.build_agent_base") as mock_build:
        mock_run.return_value = MagicMock(returncode=0)
        from packages.verification import ensure_base_image

        ensure_base_image("podman")
        mock_build.assert_not_called()


def test_ensure_base_image_builds_when_missing():
    with patch("subprocess.run") as mock_run, patch("build.build_agent_base") as mock_build:
        mock_run.return_value = MagicMock(returncode=1)
        from packages.verification import ensure_base_image

        ensure_base_image("podman")
        mock_build.assert_called_once_with("podman")


def test_ensure_base_image_handles_exception_and_builds():
    with patch("subprocess.run", side_effect=Exception("error")), patch("build.build_agent_base") as mock_build:
        from packages.verification import ensure_base_image

        ensure_base_image("podman")
        mock_build.assert_called_once_with("podman")


def test_verify_package_build_failure(tmp_path: Path):
    pkg_dir = tmp_path / "packages" / "build-fail"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "package.yaml").write_text(
        "name: build-fail\nversion: 1.0.0\nverification:\n    command: test --version\n"
    )

    with (
        patch("packages.verification.ensure_base_image"),
        patch("packages.verification.ensure_package_images"),
        patch("subprocess.run") as mock_run,
    ):
        mock_run.return_value = MagicMock(returncode=1, stdout="Layer error")
        res = verify_package("build-fail", repo_root=tmp_path)
        assert res.passed is False
        assert "Failed to assemble verification container layer" in (res.error or "")


def test_verify_package_unexpected_exception(tmp_path: Path):
    pkg_dir = tmp_path / "packages" / "err-tool"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "package.yaml").write_text(
        "name: err-tool\nversion: 1.0.0\nverification:\n    command: test --version\n"
    )

    with patch("packages.verification.ensure_base_image", side_effect=RuntimeError("disk full")):
        res = verify_package("err-tool", repo_root=tmp_path)
        assert res.passed is False
        assert "disk full" in (res.error or "")


def test_verify_packages_subset_and_all():
    with patch("packages.verification.verify_package") as mock_verify:
        mock_verify.return_value = PackageVerificationResult(
            package="p",
            command="c",
            passed=True,
            duration_ms=10.0,
            output="",
        )
        # Subset
        results = verify_packages(["gh"])
        assert len(results) == 1
        mock_verify.assert_called_with("gh", runtime="podman", repo_root=None)

        # All
        results_all = verify_packages("all")
        assert len(results_all) >= 20


def test_render_verification_results_fallback(capsys: pytest.CaptureFixture[str]):
    results = [
        PackageVerificationResult(
            package="p1",
            command="p1 --version",
            passed=True,
            duration_ms=50.0,
            output="ok",
        ),
        PackageVerificationResult(
            package="p2",
            command="p2 --version",
            passed=False,
            duration_ms=60.0,
            output="",
            error="Failed",
        ),
    ]
    with patch.dict("sys.modules", {"rich.console": None}):
        render_verification_results(results)
    captured = capsys.readouterr().out
    assert "[PASS] p1" in captured
    assert "[FAIL] p2" in captured


def test_execute_test_cli():
    from build import execute_test
    from cli import TestOptions
    from util import EnvironmentError

    # Environment error
    with patch("build.validate_environment", side_effect=EnvironmentError("No podman")):
        opts = TestOptions(packages="all")
        assert execute_test(opts) == 1

    # Unknown package
    with patch("build.validate_environment", return_value="podman"):
        opts = TestOptions(packages="nonexistent_pkg_abc")
        assert execute_test(opts) == 1

    # Success
    with (
        patch("build.validate_environment", return_value="podman"),
        patch("packages.verify_packages") as mock_verify,
        patch("packages.render_verification_results"),
    ):
        mock_verify.return_value = [
            PackageVerificationResult(
                package="gh",
                command="gh --version",
                passed=True,
                duration_ms=100.0,
                output="gh version 2.0.0",
            )
        ]
        opts = TestOptions(packages="gh")
        assert execute_test(opts) == 0

    # Failure in test
    with (
        patch("build.validate_environment", return_value="podman"),
        patch("packages.verify_packages") as mock_verify,
        patch("packages.render_verification_results"),
    ):
        mock_verify.return_value = [
            PackageVerificationResult(
                package="gh",
                command="gh --version",
                passed=False,
                duration_ms=100.0,
                output="",
                error="boom",
            )
        ]
        opts = TestOptions(packages="gh")
        assert execute_test(opts) == 1


def test_verify_package_integration_missing_manifest(tmp_path: Path):
    res = verify_package_integration("non-existent-pkg-xyz", repo_root=tmp_path)
    assert res.passed is False
    assert "Manifest not found" in (res.error or "")


def test_verify_package_integration_disabled_skipped(tmp_path: Path):
    pkg_dir = tmp_path / "packages" / "no-int"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "package.yaml").write_text("name: no-int\nversion: 1.0.0\n")

    res = verify_package_integration("no-int", repo_root=tmp_path)
    assert res.passed is True
    assert "skipped" in res.output


def test_verify_package_integration_success_mocked(tmp_path: Path):
    import config  # noqa: F401

    pkg_dir = tmp_path / "packages" / "int-tool"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "package.yaml").write_text(
        "name: int-tool\n"
        "version: 1.0.0\n"
        "integration:\n"
        "    enabled: true\n"
        "    command: int-tool --test\n"
        "    expected_output_contains: 'integration-ok'\n"
    )

    with (
        patch("packages.verification.ensure_base_image"),
        patch("packages.verification.ensure_package_images"),
        patch("subprocess.run") as mock_run,
    ):
        build_mock = MagicMock(returncode=0, stdout="Successfully built")
        exec_mock = MagicMock(returncode=0, stdout="integration-ok 1.0")
        cleanup_mock = MagicMock(returncode=0)

        mock_run.side_effect = [build_mock, exec_mock, cleanup_mock]

        res = verify_package_integration("int-tool", repo_root=tmp_path)
        assert res.passed is True
        assert res.error is None
        assert "integration-ok" in res.output


def test_verify_package_integration_failure_mocked(tmp_path: Path):
    import config  # noqa: F401

    pkg_dir = tmp_path / "packages" / "int-fail"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "package.yaml").write_text(
        "name: int-fail\nversion: 1.0.0\nintegration:\n    enabled: true\n    command: int-fail --test\n"
    )

    with (
        patch("packages.verification.ensure_base_image"),
        patch("packages.verification.ensure_package_images"),
        patch("subprocess.run") as mock_run,
    ):
        build_mock = MagicMock(returncode=0, stdout="Successfully built")
        exec_mock = MagicMock(returncode=1, stdout="Failed integration run")
        cleanup_mock = MagicMock(returncode=0)

        mock_run.side_effect = [build_mock, exec_mock, cleanup_mock]

        res = verify_package_integration("int-fail", repo_root=tmp_path)
        assert res.passed is False
        assert "failed with exit code 1" in (res.error or "")


def test_verify_packages_integration():
    with patch("packages.verification.verify_package_integration") as mock_verify:
        mock_verify.return_value = PackageVerificationResult(
            package="podman",
            command="podman info",
            passed=True,
            duration_ms=50.0,
            output="ok",
        )
        results = verify_packages_integration(["podman"])
        assert len(results) == 1
        mock_verify.assert_called_with("podman", runtime="podman", repo_root=None)


def test_execute_test_cli_integration_flag():
    from build import execute_test
    from cli import TestOptions

    with (
        patch("build.validate_environment", return_value="podman"),
        patch("packages.verify_packages_integration") as mock_verify_int,
        patch("packages.render_verification_results") as mock_render,
    ):
        mock_verify_int.return_value = [
            PackageVerificationResult(
                package="podman",
                command="podman info",
                passed=True,
                duration_ms=100.0,
                output="nested-podman-success",
            )
        ]
        opts = TestOptions(packages="podman", integration=True)
        assert execute_test(opts) == 0
        mock_verify_int.assert_called_once_with(["podman"], runtime="podman")
        assert "Integration" in mock_render.call_args[1].get("title", "")


@pytest.mark.smoke
@pytest.mark.integration
def test_live_package_smoke():
    """Live smoke test asserting that gh verifies in-container cleanly."""
    if not shutil.which("podman"):
        pytest.skip("podman not installed")
    if os.environ.get("CI") and not os.environ.get("PA_CONTAINER_LIVE_TESTS"):
        pytest.skip("Live container tests skipped in CI without PA_CONTAINER_LIVE_TESTS=1")
    res = verify_package("gh")
    assert res.passed is True
    assert "gh version" in res.output
