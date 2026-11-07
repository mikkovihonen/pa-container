from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from llama_build import (
    LlamaBuildError,
    build_llama_server,
    check_build_prerequisites,
    detect_hardware_backend,
    find_built_binary,
    get_minimal_cmake_flags,
    resolve_latest_tag,
    sync_llama_source,
)


class TestPrerequisites:
    def test_missing_git(self):
        with patch("shutil.which", side_effect=lambda cmd: None if cmd == "git" else "/usr/bin/" + cmd):
            ok, err = check_build_prerequisites()
            assert ok is False
            assert "git not found" in err

    def test_missing_cmake(self):
        with patch("shutil.which", side_effect=lambda cmd: None if cmd == "cmake" else "/usr/bin/" + cmd):
            ok, err = check_build_prerequisites()
            assert ok is False
            assert "cmake not found" in err

    def test_missing_compiler(self):
        with patch(
            "shutil.which",
            side_effect=lambda cmd: None if cmd in ("g++", "clang++", "c++", "clang", "cc") else "/usr/bin/" + cmd,
        ):
            ok, err = check_build_prerequisites()
            assert ok is False
            assert "compiler not found" in err


class TestHardwareDetection:
    def test_override_takes_precedence(self):
        assert detect_hardware_backend("cuda") == "cuda"
        assert detect_hardware_backend("cpu") == "cpu"
        assert detect_hardware_backend("metal") == "metal"

    def test_darwin_arm64_detects_metal(self):
        with patch("sys.platform", "darwin"), patch("platform.machine", return_value="arm64"):
            assert detect_hardware_backend("auto") == "metal"

    def test_linux_cuda_detected_via_nvcc(self):
        with (
            patch("sys.platform", "linux"),
            patch("shutil.which", side_effect=lambda cmd: "/usr/local/cuda/bin/nvcc" if cmd == "nvcc" else None),
        ):
            assert detect_hardware_backend("auto") == "cuda"

    def test_linux_rocm_detected_via_hipcc(self):
        with (
            patch("sys.platform", "linux"),
            patch("shutil.which", side_effect=lambda cmd: "/opt/rocm/bin/hipcc" if cmd == "hipcc" else None),
        ):
            assert detect_hardware_backend("auto") == "rocm"

    def test_linux_fallback_to_cpu(self):
        with (
            patch("sys.platform", "linux"),
            patch("shutil.which", return_value=None),
            patch("pathlib.Path.exists", return_value=False),
        ):
            assert detect_hardware_backend("auto") == "cpu"


class TestMinimalCmakeFlags:
    def test_minimal_flags(self):
        flags = get_minimal_cmake_flags("metal", minimal=True)
        assert "-DBUILD_SHARED_LIBS=OFF" in flags
        assert "-DLLAMA_BUILD_SERVER=ON" in flags
        assert "-DLLAMA_BUILD_TOOLS=ON" in flags
        assert "-DLLAMA_BUILD_EXAMPLES=OFF" in flags
        assert "-DLLAMA_BUILD_UI=OFF" in flags
        assert "-DLLAMA_USE_PREBUILT_UI=OFF" in flags
        assert "-DLLAMA_OPENSSL=OFF" in flags
        assert "-DGGML_RPC=OFF" in flags
        assert "-DLLAMA_BUILD_TESTS=OFF" in flags
        assert "-DGGML_METAL=ON" in flags
        assert "-DGGML_METAL_EMBED_LIBRARY=ON" in flags
        assert "-DGGML_NATIVE=ON" in flags

    def test_cuda_flags(self):
        flags = get_minimal_cmake_flags("cuda", minimal=True)
        assert "-DGGML_CUDA=ON" in flags
        assert "-DGGML_NATIVE=ON" in flags

    def test_cpu_flags(self):
        flags = get_minimal_cmake_flags("cpu", minimal=True)
        assert "-DGGML_OPENMP=ON" in flags
        assert "-DGGML_NATIVE=ON" in flags

    def test_extra_flags_appended(self):
        flags = get_minimal_cmake_flags("cpu", minimal=True, extra_flags=["-DCUSTOM_FLAG=ON"])
        assert "-DCUSTOM_FLAG=ON" in flags


class TestResolveLatestTag:
    def test_resolves_from_git_ls_remote(self):
        fake_output = (
            "c13fcbf684171d5e0bca3fc5c34be6a99174b05f\trefs/tags/v0.5.0\n"
            "c4261a74a59c5a719e8f73038e28633b08f2bea4\trefs/tags/v0.9.0\n"
        )
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=["git", "ls-remote"], returncode=0, stdout=fake_output
            )
            assert resolve_latest_tag("https://example.com/repo.git") == "v0.9.0"

    def test_fallback_on_error(self):
        with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, ["git"])):
            assert resolve_latest_tag("https://example.com/repo.git") == "v0.9.0"


class TestSourceSync:
    def test_clones_when_missing(self, tmp_path: Path):
        src_dir = tmp_path / "llama.cpp"
        with patch("llama_build._run_cmd") as mock_run:
            sync_llama_source("https://example.com/llama.cpp.git", "v0.9.0", src_dir)
            mock_run.assert_called_once()
            cmd = mock_run.call_args[0][0]
            assert cmd[:4] == ["git", "clone", "--depth", "1"]
            assert "v0.9.0" in cmd

    def test_fetches_when_git_dir_exists(self, tmp_path: Path):
        src_dir = tmp_path / "llama.cpp"
        (src_dir / ".git").mkdir(parents=True)
        with patch("llama_build._run_cmd") as mock_run:
            sync_llama_source("https://example.com/llama.cpp.git", "v0.9.0", src_dir)
            assert mock_run.call_count == 3
            remote_cmd = mock_run.call_args_list[0][0][0]
            fetch_cmd = mock_run.call_args_list[1][0][0]
            checkout_cmd = mock_run.call_args_list[2][0][0]
            assert remote_cmd == ["git", "remote", "set-url", "origin", "https://example.com/llama.cpp.git"]
            assert fetch_cmd[:4] == ["git", "fetch", "--depth", "1"]
            assert "+refs/tags/v0.9.0:refs/tags/v0.9.0" in fetch_cmd
            assert checkout_cmd == ["git", "checkout", "v0.9.0"]


class TestFindBuiltBinary:
    def test_finds_in_bin(self, tmp_path: Path):
        bin_path = tmp_path / "bin" / "llama-server"
        bin_path.parent.mkdir(parents=True)
        bin_path.write_text("#!/bin/sh\n")
        bin_path.chmod(0o755)

        found = find_built_binary(tmp_path)
        assert found == bin_path

    def test_missing_raises_error(self, tmp_path: Path):
        with pytest.raises(LlamaBuildError, match="llama-server executable not found"):
            find_built_binary(tmp_path)


class TestBuildLlamaServer:
    def test_end_to_end_mocked(self, tmp_path: Path):
        src_dir = tmp_path / "src"
        bin_dir = tmp_path / "bin"
        src_dir.mkdir(parents=True)
        bin_dir.mkdir(parents=True)

        fake_binary = src_dir / "build" / "bin" / "llama-server"
        fake_binary.parent.mkdir(parents=True)
        fake_binary.write_text("#!/bin/sh\necho llama.cpp version 1.0\n")
        fake_binary.chmod(0o755)

        def fake_run(cmd, cwd=None, label="command"):
            if label == "cmake build":
                fake_binary.parent.mkdir(parents=True, exist_ok=True)
                fake_binary.write_text("#!/bin/sh\necho llama.cpp version 1.0\n")
                fake_binary.chmod(0o755)

        with (
            patch("llama_build.check_build_prerequisites", return_value=(True, None)),
            patch("llama_build.sync_llama_source"),
            patch("llama_build._run_cmd", side_effect=fake_run),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = subprocess.CompletedProcess(args=["--version"], returncode=0, stdout="llama 1.0")
            result = build_llama_server(
                backend="cpu",
                src_dir=src_dir,
                bin_dir=bin_dir,
            )
            assert result == bin_dir / "llama-server"
            assert result.is_file()
            assert os.access(result, os.X_OK)

    def test_clean_by_default_removes_build_dir(self, tmp_path: Path):
        src_dir = tmp_path / "src"
        bin_dir = tmp_path / "bin"
        build_dir = src_dir / "build"
        build_dir.mkdir(parents=True)
        (build_dir / "old_cache.txt").write_text("old")

        with (
            patch("llama_build.check_build_prerequisites", return_value=(True, None)),
            patch("llama_build.sync_llama_source"),
            patch("llama_build._run_cmd"),
            patch("llama_build.find_built_binary") as mock_find,
            patch("subprocess.run"),
        ):
            fake_bin = tmp_path / "fake-llama"
            fake_bin.write_text("fake")
            fake_bin.chmod(0o755)
            mock_find.return_value = fake_bin

            build_llama_server(src_dir=src_dir, bin_dir=bin_dir, clean=True)
            assert not (build_dir / "old_cache.txt").exists()

    def test_resolves_latest_tag_when_requested(self, tmp_path: Path):
        src_dir = tmp_path / "src"
        bin_dir = tmp_path / "bin"
        with (
            patch("llama_build.check_build_prerequisites", return_value=(True, None)),
            patch("llama_build.resolve_latest_tag", return_value="v0.9.0") as mock_resolve,
            patch("llama_build.sync_llama_source") as mock_sync,
            patch("llama_build._run_cmd"),
            patch("llama_build.find_built_binary") as mock_find,
            patch("subprocess.run"),
        ):
            fake_bin = tmp_path / "fake-llama"
            fake_bin.write_text("fake")
            fake_bin.chmod(0o755)
            mock_find.return_value = fake_bin

            build_llama_server(src_dir=src_dir, bin_dir=bin_dir, tag="latest")
            mock_resolve.assert_called_once()
            mock_sync.assert_called_once_with(
                repo_url="https://github.com/ggml-org/llama.cpp.git",
                tag="v0.9.0",
                src_dir=src_dir,
            )
