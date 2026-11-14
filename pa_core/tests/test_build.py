"""
Unit tests for pa_core/build.py

Run with:
    python -m pytest pa_core/tests/test_build.py -v
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Import build module functions — we patch the heavy deps (subprocess, validate_environment)
from build import (
    PROXY_IMAGE_TAG,
    REPO_ROOT,
    build_agent,
    build_project_image,
    build_proxy,
    main,
)

# ---------------------------------------------------------------------------
# build_proxy / build_agent
# ---------------------------------------------------------------------------


class TestBuildProxy:
    def _mock_popen(self):
        """Return a mock Popen that completes successfully with no output."""
        mock_process = MagicMock()
        mock_process.__enter__.return_value = mock_process
        mock_process.stdout = iter([])
        mock_process.communicate.return_value = ("", "")
        mock_process.wait.return_value = 0
        return mock_process

    @pytest.fixture(autouse=True)
    def _mock_package_builds(self):
        yield

    def test_calls_runtime_build(self):
        """build_proxy should invoke the container runtime with correct args."""
        with patch("build.subprocess.Popen", return_value=self._mock_popen()) as mock_popen:
            build_proxy("podman")
            build_calls = [c for c in mock_popen.call_args_list if c[0][0][0] == "podman"]
            assert len(build_calls) == 1
            cmd = build_calls[0][0][0]
            assert cmd[0] == "podman"
            assert cmd[1] == "build"
            assert "--force-rm" in cmd
            assert "--tag" in cmd
            assert "pa-container-agent-proxy:local" in cmd
            # Should include the Containerfile path
            assert any("Containerfile" in str(c) for c in cmd)
            # Should include the repo root as build context
            assert str(REPO_ROOT) in cmd

    def test_uses_passed_tag(self):
        with patch("build.subprocess.Popen", return_value=self._mock_popen()) as mock_popen:
            build_proxy("podman")
            cmd = mock_popen.call_args[0][0]
            tag_idx = cmd.index("--tag")
            assert cmd[tag_idx + 1] == PROXY_IMAGE_TAG

    def test_includes_build_time_label(self):
        """build_proxy should set pa-container.build.time label."""
        with patch("build.subprocess.Popen", return_value=self._mock_popen()) as mock_popen:
            build_proxy("podman")
            cmd = mock_popen.call_args[0][0]
            assert "--label" in cmd
            labels = [cmd[i + 1] for i, c in enumerate(cmd) if c == "--label"]
            assert any(lbl.startswith("pa-container.build.time=") for lbl in labels)
            assert any(lbl == "pa-container.type=shared" for lbl in labels)

    def test_includes_shared_type_label(self):
        """build_proxy should set pa-container.type=shared label."""
        with patch("build.subprocess.Popen", return_value=self._mock_popen()) as mock_popen:
            build_proxy("podman")
            cmd = mock_popen.call_args[0][0]
            labels = [cmd[i + 1] for i, c in enumerate(cmd) if c == "--label"]
            assert "pa-container.type=shared" in labels

    def test_includes_hash_label(self):
        """build_proxy should set pa-container.hash label with content hash."""
        with patch("build.subprocess.Popen", return_value=self._mock_popen()) as mock_popen:
            build_proxy("podman")
            cmd = mock_popen.call_args[0][0]
            labels = [cmd[i + 1] for i, c in enumerate(cmd) if c == "--label"]
            assert any(lbl.startswith("pa-container.hash=") for lbl in labels)

    def test_build_agent_calls_runtime(self):
        """build_agent should invoke the container runtime with correct args."""
        with (
            patch("build.build_agent_base", return_value="pa-container-agent-base:local"),
            patch("build.subprocess.Popen", return_value=self._mock_popen()) as mock_popen,
        ):
            build_agent("podman")
            mock_popen.assert_called_once()
            cmd = mock_popen.call_args[0][0]
            assert cmd[0] == "podman"
            assert cmd[1] == "build"
            assert "pa-container-agent:local" in cmd
            assert any("Containerfile" in str(c) for c in cmd)

    def test_build_agent_labels_image_as_shared(self):
        """The shared base must be labelled `shared`, never `project`."""
        with (
            patch("build.build_agent_base", return_value="pa-container-agent-base:local"),
            patch("build.subprocess.Popen", return_value=self._mock_popen()) as mock_popen,
        ):
            build_agent("podman")
            cmd = mock_popen.call_args[0][0]
            labels = [cmd[i + 1] for i, c in enumerate(cmd) if c == "--label"]
            assert "pa-container.type=shared" in labels
            assert "pa-container.type=project" not in labels

    def test_build_agent_installs_distro_packages(self):
        """build_agent should include microdnf install for distro packages in CORE_PACKAGES."""
        captured_cf = []

        def capture_popen(cmd, *a, **kw):
            cf_path = cmd[cmd.index("--file") + 1]
            captured_cf.append(Path(cf_path).read_text())
            return self._mock_popen()

        with (
            patch("build.build_agent_base", return_value="pa-container-agent-base:local"),
            patch("build.subprocess.Popen", side_effect=capture_popen),
        ):
            build_agent("podman")
            assert len(captured_cf) == 1
            assert "microdnf install -y --nodocs" in captured_cf[0]
            assert "python3" in captured_cf[0]
            assert "uv" in captured_cf[0]

    def test_containerfile_does_not_hardcode_type_label(self):
        from build import REPO_ROOT

        containerfile = (REPO_ROOT / "coding-agent" / "Containerfile").read_text()
        assert "LABEL pa-container.type" not in containerfile


class TestBuildAgentBase:
    """Tests for build_agent_base() — the base runner image."""

    @staticmethod
    def _mock_popen():
        mock_process = MagicMock()
        mock_process.stdout = iter([])
        mock_process.wait.return_value = 0
        return mock_process

    def test_builds_the_agent_base_containerfile(self):
        import build as build_mod

        with patch("build.subprocess.Popen", return_value=self._mock_popen()) as mock_popen:
            tag = build_mod.build_agent_base("podman")
            assert tag == build_mod.AGENT_BASE_IMAGE_TAG
            cmd = mock_popen.call_args[0][0]
            assert cmd[:2] == ["podman", "build"]
            assert build_mod.AGENT_BASE_IMAGE_TAG in cmd
            assert any("coding-agent" in str(c) and "Containerfile" in str(c) for c in cmd)

    def test_carries_a_build_time_label(self):
        import build as build_mod

        with patch("build.subprocess.Popen", return_value=self._mock_popen()) as mock_popen:
            build_mod.build_agent_base("podman")
            cmd = mock_popen.call_args[0][0]
            labels = [cmd[i + 1] for i, c in enumerate(cmd) if c == "--label"]
            assert any(lbl.startswith("pa-container.build.time=") for lbl in labels)
            assert "pa-container.type=base" in labels

    def test_uniform_base_image_tag(self):
        import build as build_mod

        with patch("build.subprocess.Popen", return_value=self._mock_popen()):
            tag = build_mod.build_agent_base("podman")
            assert tag == build_mod.AGENT_BASE_IMAGE_TAG


# ---------------------------------------------------------------------------
# _build_dns_args
# ---------------------------------------------------------------------------


class TestBuildDNSArgs:
    def test_default_is_1_1_1_1(self, monkeypatch):
        import build

        monkeypatch.delenv("BUILD_DNS", raising=False)
        assert build._build_dns_args() == ["--dns", "1.1.1.1"]

    def test_custom_single_server(self, monkeypatch):
        import build

        monkeypatch.setenv("BUILD_DNS", "8.8.8.8")
        assert build._build_dns_args() == ["--dns", "8.8.8.8"]

    def test_multiple_servers(self, monkeypatch):
        import build

        monkeypatch.setenv("BUILD_DNS", "1.1.1.1, 8.8.8.8")
        assert build._build_dns_args() == ["--dns", "1.1.1.1", "--dns", "8.8.8.8"]

    def test_disabled_values(self, monkeypatch):
        import build

        for disabled in ("", "none", "off", "0", "false"):
            monkeypatch.setenv("BUILD_DNS", disabled)
            assert build._build_dns_args() == []


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


class TestMain:
    def test_main_builds_all_images(self):
        """main should build the proxy, then the agent."""
        calls = []
        with (
            patch("build.validate_environment", return_value="podman"),
            patch("build.check_build_memory", return_value=True),
            patch("build.build_proxy", side_effect=lambda r: calls.append("proxy")),
            patch("build.build_agent", side_effect=lambda r: calls.append("agent")),
            patch("images.prune_dangling_images") as mock_prune,
            patch("sys.exit"),
        ):
            main([])
        assert calls == ["proxy", "agent"]
        mock_prune.assert_called_once_with("podman", purge_cache=False)

    def test_main_clean_runs_all_cleanups(self):
        with (
            patch("build.validate_environment", return_value="podman"),
            patch("containers.cleanup_orphaned_agent_containers", return_value=["agent-1"]) as mock_ctr,
            patch("images.cleanup_orphaned_project_images", return_value=["proj-1"]) as mock_img,
            patch("images.prune_dangling_images", return_value=["layer-1"]) as mock_prune,
            patch("build.build_proxy") as mock_proxy,
            patch("build.build_agent") as mock_agent,
        ):
            main(["--clean"])
            mock_ctr.assert_called_once_with("podman")
            mock_img.assert_called_once_with("podman")
            mock_prune.assert_called_once_with("podman", purge_cache=True)
            mock_proxy.assert_not_called()
            mock_agent.assert_not_called()

    def test_main_no_prune_skips_pruning(self):
        with (
            patch("build.validate_environment", return_value="podman"),
            patch("build.check_build_memory", return_value=True),
            patch("build.build_proxy"),
            patch("build.build_agent"),
            patch("images.prune_dangling_images") as mock_prune,
        ):
            main(["--no-prune"])
            mock_prune.assert_not_called()

    def test_main_stops_before_building_when_memory_is_short(self):
        with (
            patch("build.validate_environment", return_value="podman"),
            patch("build.check_build_memory", return_value=False),
            patch("build.build_proxy") as mock_proxy,
            patch("build.build_agent") as mock_agent,
            patch("sys.exit", side_effect=SystemExit(1)),
            pytest.raises(SystemExit),
        ):
            main()
        mock_proxy.assert_not_called()
        mock_agent.assert_not_called()

    def test_main_exits_on_environment_error(self):
        from util import EnvironmentError

        exit_calls = []

        def track_exit(code=0):
            exit_calls.append(code)
            raise SystemExit(code)

        with (
            patch("build.validate_environment", side_effect=EnvironmentError("test error")),
            patch("sys.exit", side_effect=track_exit),
            patch("builtins.print"),
            pytest.raises(SystemExit),
        ):
            main()
        assert exit_calls == [1]

    def test_main_exits_on_build_failure(self):
        import subprocess

        with (
            patch("build.validate_environment", return_value="podman"),
            patch("build.check_build_memory", return_value=True),
            patch("build.build_proxy", side_effect=subprocess.CalledProcessError(1, "cmd")),
            patch("build.build_agent"),
            patch("sys.exit") as mock_exit,
            patch("builtins.print"),
        ):
            main()
            mock_exit.assert_called_once_with(1)

    def test_main_exits_on_file_not_found(self):
        with (
            patch("build.validate_environment", return_value="nonexistent_runtime"),
            patch("build.check_build_memory", return_value=True),
            patch("build.build_proxy", side_effect=FileNotFoundError),
            patch("build.build_agent"),
            patch("sys.exit") as mock_exit,
            patch("builtins.print"),
        ):
            main()
            mock_exit.assert_called_once_with(1)


# ---------------------------------------------------------------------------
# build_project_image
# ---------------------------------------------------------------------------


class TestBuildProjectImage:
    def _mock_popen(self):
        """Return a mock Popen that completes successfully with no output."""
        mock_process = MagicMock()
        mock_process.__enter__.return_value = mock_process
        mock_process.stdout = iter([])
        mock_process.communicate.return_value = ("", "")
        mock_process.wait.return_value = 0
        return mock_process

    @pytest.fixture(autouse=True)
    def _mock_prereqs(self):
        with (
            patch("build.build_agent_base", return_value="pa-container-agent-base:local"),
            patch("packages.ensure_package_images"),
        ):
            yield

    def test_build_project_image_calls_runtime(self):
        """build_project_image should invoke the container runtime with correct args."""
        with patch("build.subprocess.Popen", return_value=self._mock_popen()) as mock_popen:
            build_project_image(
                "podman",
                "/path/to/root/commands.sh",
                "pa-container-agent-test.local",
                "abc123",
            )
            mock_popen.assert_called_once()
            cmd = mock_popen.call_args[0][0]
            assert cmd[0] == "podman"
            assert cmd[1] == "build"
            assert "--force-rm" in cmd
            assert "--tag" in cmd
            assert "pa-container-agent-test.local" in cmd
            assert any("Containerfile" in str(c) for c in cmd)

    def test_build_project_image_includes_project_hash(self):
        """When project_hash is provided, it should be in the generated Containerfile."""
        captured_cf = []

        def capture_popen(cmd, *a, **kw):
            cf_path = cmd[cmd.index("--file") + 1]
            captured_cf.append(Path(cf_path).read_text())
            return self._mock_popen()

        with patch("build.subprocess.Popen", side_effect=capture_popen):
            build_project_image(
                "podman",
                "/path/to/root/commands.sh",
                "pa-container-project-a1b2c-d4e5f.local",
                "abc123",
                project_hash="a1b2c",
                build_timestamp="2025-01-01T00:00:00Z",
            )
            assert len(captured_cf) == 1
            assert 'LABEL pa-container.project.hash="a1b2c"' in captured_cf[0]
            assert 'LABEL pa-container.build.time="2025-01-01T00:00:00Z"' in captured_cf[0]
            assert 'LABEL pa-container.hash="abc123"' in captured_cf[0]

    def test_build_project_image_with_packages(self):
        """When packages are provided, they should be composed from pre-built capability images."""
        captured_cf = []

        def capture_popen(cmd, *a, **kw):
            cf_path = cmd[cmd.index("--file") + 1]
            captured_cf.append(Path(cf_path).read_text())
            return self._mock_popen()

        with (
            patch("packages.ensure_package_images") as mock_ensure,
            patch("build.subprocess.Popen", side_effect=capture_popen),
        ):
            build_project_image(
                "podman",
                "/path/to/root/commands.sh",
                "test.local",
                "abc123",
                packages=["languages/go", "languages/rust"],
            )
            mock_ensure.assert_called_once()
            assert "COPY --from=pa-container-pkg-languages-go" in captured_cf[0]
            assert "COPY --from=pa-container-pkg-languages-rust" in captured_cf[0]

    def test_build_project_image_legacy_fallback(self):
        """When use_prebuilt=False, fallback to inline multi-stage dynamic build."""
        captured_cf = []

        def capture_popen(cmd, *a, **kw):
            cf_path = cmd[cmd.index("--file") + 1]
            captured_cf.append(Path(cf_path).read_text())
            return self._mock_popen()

        with (
            patch("build.subprocess.Popen", side_effect=capture_popen),
        ):
            build_project_image(
                "podman",
                "/path/to/root/commands.sh",
                "test.local",
                "abc123",
                packages=["languages/go", "languages/rust"],
                use_prebuilt=False,
            )
            assert "COPY --from=artifact-languages-go /out/languages-go/ /" in captured_cf[0]
            assert "COPY --from=artifact-languages-rust /out/languages-rust/ /" in captured_cf[0]

    def test_build_project_image_with_distro_packages(self):
        """When distro packages are required, a unified microdnf install command is generated."""
        captured_cf = []

        def capture_popen(cmd, *a, **kw):
            cf_path = cmd[cmd.index("--file") + 1]
            captured_cf.append(Path(cf_path).read_text())
            return self._mock_popen()

        with (
            patch("packages.ensure_package_images"),
            patch("build.subprocess.Popen", side_effect=capture_popen),
        ):
            build_project_image(
                "podman",
                "/path/to/root/commands.sh",
                "test.local",
                "abc123",
                packages=["languages/python"],
            )
            cf = captured_cf[0]
            assert "python3" in cf
            assert "uv" in cf
            assert "COPY --from=pa-container-pkg-languages-python" in cf

    def test_build_project_image_without_distro_packages(self):
        """When no runtime distro packages are needed, runner stage omits distro install."""
        captured_cf = []

        def capture_popen(cmd, *a, **kw):
            cf_path = cmd[cmd.index("--file") + 1]
            captured_cf.append(Path(cf_path).read_text())
            return self._mock_popen()

        with (
            patch("packages.builder.collect_distro_packages", return_value=[]),
            patch("packages.ensure_package_images"),
            patch("build.subprocess.Popen", side_effect=capture_popen),
        ):
            build_project_image(
                "podman",
                "/path/to/root/commands.sh",
                "test.local",
                "abc123",
            )
            # Runner stage should not contain runner microdnf install
            cf = captured_cf[0]
            assert "microdnf install" not in cf

    def test_build_project_image_automatically_includes_core_packages(self, tmp_path):
        """build_project_image should automatically include core packages (e.g. languages/python) even when not requested."""
        proj_dir = tmp_path / "project"
        proj_dir.mkdir()
        cfg_dir = proj_dir / ".pa-container"
        cfg_dir.mkdir()
        (cfg_dir / "config.yaml").write_text("packages: ['git']\n")

        captured_cf = []

        def capture_popen(cmd, *a, **kw):
            cf_path = cmd[cmd.index("--file") + 1]
            captured_cf.append(Path(cf_path).read_text())
            return self._mock_popen()

        with (
            patch("packages.ensure_package_images"),
            patch("build.subprocess.Popen", side_effect=capture_popen),
        ):
            build_project_image(
                "podman",
                "/path/to/root/commands.sh",
                "test.local",
                "abc123",
                project_path=str(proj_dir),
            )

            cf = captured_cf[0]
            assert "COPY --from=pa-container-pkg-git" in cf
            assert "COPY --from=pa-container-pkg-languages-python" in cf

    def test_build_project_image_builds_base(self):
        """build_project_image ensures base image is built."""
        with (
            patch("build.build_agent_base", return_value="pa-container-agent-base:local") as mock_base,
            patch("build.subprocess.Popen", return_value=self._mock_popen()),
        ):
            build_project_image(
                "podman",
                "/path/to/root/commands.sh",
                "test.local",
                "abc123",
            )
            mock_base.assert_called_once_with("podman")


class TestMainWithPackages:
    def test_main_with_packages_flag(self):
        from build import main

        built = []
        with (
            patch("build.validate_environment", return_value="podman"),
            patch("build.check_build_memory", return_value=True),
            patch("packages.build_package", side_effect=lambda pkg, **kw: built.append(pkg)),
        ):
            main(["--packages", "languages/c-cpp,git"])
            assert built == ["languages/c-cpp", "git"] or built == ["git", "languages/c-cpp"]

    def test_main_with_packages_features_rejected(self):
        from build import main

        with (
            patch("build.validate_environment", return_value="podman"),
            patch("build.check_build_memory", return_value=True),
            pytest.raises(SystemExit),
        ):
            main(["--packages", "git+github"])

    def test_main_with_packages_canonical(self):
        from build import main

        built_calls = []
        with (
            patch("build.validate_environment", return_value="podman"),
            patch("build.check_build_memory", return_value=True),
            patch("packages.build_package", side_effect=lambda pkg, **kw: built_calls.append((pkg, kw))),
        ):
            main(["--packages", "source-control/github"])
            assert len(built_calls) == 1
            assert built_calls[0][0] == "source-control/github"

    def test_main_with_packages_all(self):
        from build import main
        from packages import discover_packages

        built = []
        with (
            patch("build.validate_environment", return_value="podman"),
            patch("build.check_build_memory", return_value=True),
            patch("packages.build_package", side_effect=lambda pkg, **kw: built.append(pkg)),
        ):
            main(["--packages", "all"])
            assert len(built) == len(discover_packages())

    def test_main_with_unknown_package(self):
        import sys

        from build import main

        with (
            patch("build.validate_environment", return_value="podman"),
            patch("build.check_build_memory", return_value=True),
            patch.object(sys, "exit", side_effect=SystemExit(1)),
        ):
            with pytest.raises(SystemExit) as exc_info:
                main(["--packages", "unknown_pkg"])
            assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# Build-memory preflight
# ---------------------------------------------------------------------------

_MEMINFO = """MemTotal:        1984568 kB
MemFree:           44404 kB
MemAvailable:     302080 kB
Buffers:            1234 kB
"""


class TestParseMemAvailable:
    def test_reads_mem_available_not_mem_free(self):
        """MemFree and MemAvailable differ by an order of magnitude on a warm
        builder; the reclaimable page cache is usable, so MemAvailable is right."""
        from build import _parse_mem_available_mib

        assert _parse_mem_available_mib(_MEMINFO) == 302080 // 1024

    def test_returns_none_when_absent(self):
        from build import _parse_mem_available_mib

        assert _parse_mem_available_mib("MemTotal: 123 kB\n") is None


class TestReadAvailableMemoryMib:
    def test_asks_the_vm_when_there_is_no_local_procfs(self, monkeypatch):
        """On macOS the build happens inside podman's VM, so the host's own free
        memory is irrelevant — the VM must be the one asked."""
        import build

        monkeypatch.setattr(build.Path, "exists", lambda self: False)
        seen = {}

        def mock_run(cmd, **kwargs):
            seen["cmd"] = cmd
            return MagicMock(returncode=0, stdout=_MEMINFO, stderr="")

        monkeypatch.setattr(build.subprocess, "run", mock_run)
        assert build.read_available_memory_mib("podman") == 295
        assert seen["cmd"][:3] == ["podman", "machine", "ssh"]

    def test_returns_none_when_vm_unreachable(self, monkeypatch):
        import build

        monkeypatch.setattr(build.Path, "exists", lambda self: False)
        monkeypatch.setattr(
            build.subprocess, "run", lambda cmd, **kw: MagicMock(returncode=125, stdout="", stderr="no machine")
        )
        assert build.read_available_memory_mib("podman") is None


class TestCheckBuildMemory:
    def test_passes_when_memory_is_sufficient(self, monkeypatch):
        import build

        monkeypatch.delenv("PYTHON_OPTIMIZE", raising=False)
        monkeypatch.delenv("PA_MEMORY_PREFLIGHT", raising=False)
        monkeypatch.setattr(build, "read_available_memory_mib", lambda rt: 4096)
        assert build.check_build_memory("podman") is True

    def test_blocks_the_build_when_memory_is_short(self, monkeypatch):
        """The point of the check: say so BEFORE the build starts."""
        import build

        monkeypatch.delenv("PYTHON_OPTIMIZE", raising=False)
        monkeypatch.delenv("PA_MEMORY_PREFLIGHT", raising=False)
        monkeypatch.setattr(build, "read_available_memory_mib", lambda rt: 276)
        assert build.check_build_memory("podman") is False

    def test_warns_but_proceeds_when_not_fatal(self, monkeypatch):
        """run.py's project-image build normally reuses the cached Python layer,
        so a short-memory reading there is advisory, not a stop."""
        import build

        monkeypatch.delenv("PYTHON_OPTIMIZE", raising=False)
        monkeypatch.delenv("PA_MEMORY_PREFLIGHT", raising=False)
        monkeypatch.setattr(build, "read_available_memory_mib", lambda rt: 276)
        assert build.check_build_memory("podman", fatal=False) is True

    def test_package_memory_preflight(self, monkeypatch):
        import build

        monkeypatch.delenv("PA_MEMORY_PREFLIGHT", raising=False)
        monkeypatch.setattr(build, "read_available_memory_mib", lambda rt: 1024)
        assert build.check_build_memory("podman", packages=["podman"]) is False
        monkeypatch.setattr(build, "read_available_memory_mib", lambda rt: 2500)
        assert build.check_build_memory("podman", packages=["podman"]) is True

    def test_escape_hatch_skips_the_check(self, monkeypatch):
        import build

        monkeypatch.setenv("PA_MEMORY_PREFLIGHT", "0")

        def unexpected(rt):
            raise AssertionError("memory must not be read when the preflight is disabled")

        monkeypatch.setattr(build, "read_available_memory_mib", unexpected)
        assert build.check_build_memory("podman") is True

    def test_unknown_memory_does_not_block(self, monkeypatch):
        """A reading we cannot take must never stop a build that might be fine."""
        import build

        monkeypatch.delenv("PA_MEMORY_PREFLIGHT", raising=False)
        monkeypatch.setattr(build, "read_available_memory_mib", lambda rt: None)
        assert build.check_build_memory("podman") is True


# ---------------------------------------------------------------------------
# Package declarations: ACP packages validation
# ---------------------------------------------------------------------------


class TestPackageManifestsAreValid:
    def test_all_discovered_packages_have_valid_manifests(self):
        from packages import discover_packages

        pkgs = discover_packages()
        assert len(pkgs) >= 20, f"Expected at least 20 packages, found {len(pkgs)}"
        for name, manifest in pkgs.items():
            assert manifest.name == name
            assert manifest.version
            assert manifest.description
            assert manifest.payload.type in ("binary_download", "build_script", "distro_package", "none")
            if manifest.skill.enabled:
                assert manifest.skill.source


class TestLlamaBuildArgs:
    def test_parse_args_llama_flag(self):
        import build

        args = build.parse_args(["--llama"])
        assert args.llama is True
        assert args.llama_backend is None
        assert args.llama_tag is None
        assert args.no_clean is False

    def test_parse_args_llama_options(self):
        import build

        args = build.parse_args(
            [
                "--llama",
                "--llama-backend",
                "cuda",
                "--llama-tag",
                "v0.9.0",
                "--no-clean",
                "--cmake-arg=-DTEST_1=ON",
                "--cmake-arg=-DTEST_2=OFF",
            ]
        )
        assert args.llama is True
        assert args.llama_backend == "cuda"
        assert args.llama_tag == "v0.9.0"
        assert args.no_clean is True
        assert args.cmake_args == ["-DTEST_1=ON", "-DTEST_2=OFF"]

    def test_main_invokes_llama_build(self):
        import build

        with patch("llama_build.build_llama_server", return_value=Path("/tmp/llama-server")) as mock_build:
            build.main(["--llama", "--llama-backend", "metal", "--llama-tag", "v0.9.0"])
            mock_build.assert_called_once()
            kwargs = mock_build.call_args[1]
            assert kwargs["backend"] == "metal"
            assert kwargs["tag"] == "v0.9.0"
            assert kwargs["clean"] is True

    def test_main_invokes_llama_latest(self):
        import build

        with patch("llama_build.build_llama_server", return_value=Path("/tmp/llama-server")) as mock_build:
            build.main(["--llama-latest"])
            mock_build.assert_called_once()
            kwargs = mock_build.call_args[1]
            assert kwargs["tag"] == "latest"
            assert kwargs["clean"] is True

    def test_main_no_clean_flag(self):
        import build

        with patch("llama_build.build_llama_server", return_value=Path("/tmp/llama-server")) as mock_build:
            build.main(["--llama", "--no-clean"])
            mock_build.assert_called_once()
            kwargs = mock_build.call_args[1]
            assert kwargs["clean"] is False
