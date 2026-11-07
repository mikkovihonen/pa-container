from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True

from logging_driver import LogCategory, get_category_logger

logger = get_category_logger(__name__, LogCategory.BUILD)

DEFAULT_REPO_URL = "https://github.com/ggml-org/llama.cpp.git"
DEFAULT_TAG = "v0.9.0"
DEFAULT_CACHE_DIR = Path.home() / ".cache" / "pa-container"
DEFAULT_SRC_DIR = DEFAULT_CACHE_DIR / "src" / "llama.cpp"
DEFAULT_BIN_DIR = DEFAULT_CACHE_DIR / "bin"
DEFAULT_OUTPUT_BIN = DEFAULT_BIN_DIR / "llama-server"


class LlamaBuildError(Exception):
    """Raised when building llama-server fails."""


def resolve_latest_tag(repo_url: str = DEFAULT_REPO_URL) -> str:
    """Query remote git repository for the latest semantic release tag."""
    logger.info(f"Querying latest release tag from {repo_url}...")
    try:
        res = subprocess.run(
            ["git", "ls-remote", "--tags", "--refs", "--sort=v:refname", repo_url, "v*"],
            capture_output=True,
            text=True,
            check=True,
            timeout=15,
        )
        lines = [line.strip() for line in res.stdout.strip().splitlines() if line.strip()]
        if lines:
            tag = lines[-1].split("refs/tags/")[-1].strip()
            if tag:
                logger.info(f"Resolved latest llama.cpp tag: {tag}")
                return tag
    except Exception as e:
        logger.warning(f"Failed to query latest tag from {repo_url}: {e}. Falling back to default {DEFAULT_TAG}.")
    return DEFAULT_TAG


def check_build_prerequisites() -> tuple[bool, str | None]:
    """Verify that git, cmake, and a C++ compiler are installed on the host."""
    if shutil.which("git") is None:
        return False, "git not found. Please install git."

    if shutil.which("cmake") is None:
        install_hint = "brew install cmake" if sys.platform == "darwin" else "sudo apt install cmake"
        return False, f"cmake not found. Please install CMake ({install_hint})."

    # Check for C++ compiler
    if sys.platform == "darwin":
        has_compiler = shutil.which("clang++") or shutil.which("clang") or shutil.which("cc")
        if not has_compiler:
            return False, "C++ compiler not found. Please install Xcode Command Line Tools: xcode-select --install"
    else:
        has_compiler = shutil.which("g++") or shutil.which("clang++") or shutil.which("c++")
        if not has_compiler:
            return False, "C++ compiler not found. Please install build tools (sudo apt install build-essential)."

    return True, None


def detect_hardware_backend(override: str | None = None) -> str:
    """Detect the optimal hardware acceleration backend on the host."""
    if override and override.lower() != "auto":
        return override.lower()

    if sys.platform == "darwin":
        # Apple Silicon natively supports Metal acceleration
        if platform.machine() == "arm64":
            return "metal"
        # Intel Mac fallback
        return "metal"

    if sys.platform.startswith("linux"):
        if shutil.which("nvcc") is not None or Path("/usr/local/cuda/bin/nvcc").exists():
            return "cuda"
        if shutil.which("hipcc") is not None:
            return "rocm"
        return "cpu"

    return "cpu"


def get_minimal_cmake_flags(
    backend: str,
    minimal: bool = True,
    extra_flags: list[str] | None = None,
) -> list[str]:
    """Assemble the minimal CMake configuration flags targeting llama-server."""
    flags: list[str] = [
        "-DCMAKE_BUILD_TYPE=Release",
        "-DBUILD_SHARED_LIBS=OFF",
    ]

    if minimal:
        # Strip all features unnecessary for pa-container's automated loopback daemon.
        flags.extend(
            [
                "-DLLAMA_BUILD_SERVER=ON",
                "-DLLAMA_BUILD_TOOLS=ON",
                "-DLLAMA_BUILD_EXAMPLES=OFF",
                "-DLLAMA_BUILD_TESTS=OFF",
                "-DLLAMA_BUILD_UI=OFF",
                "-DLLAMA_USE_PREBUILT_UI=OFF",
                "-DLLAMA_OPENSSL=OFF",
                "-DGGML_RPC=OFF",
            ]
        )

    b = backend.lower()
    if b == "metal":
        flags.extend(
            [
                "-DGGML_METAL=ON",
                "-DGGML_METAL_EMBED_LIBRARY=ON",
                "-DGGML_NATIVE=ON",
            ]
        )
    elif b == "cuda":
        flags.extend(
            [
                "-DGGML_CUDA=ON",
                "-DGGML_NATIVE=ON",
            ]
        )
    elif b == "rocm":
        flags.extend(
            [
                "-DGGML_HIP=ON",
                "-DGGML_NATIVE=ON",
            ]
        )
    else:  # CPU fallback
        flags.extend(
            [
                "-DGGML_NATIVE=ON",
                "-DGGML_OPENMP=ON",
            ]
        )

    if extra_flags:
        flags.extend(extra_flags)

    return flags


def _run_cmd(cmd: list[str], cwd: Path | None = None, label: str = "command") -> None:
    """Execute subprocess command logging output at INFO."""
    logger.info(f"Running [{label}]: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=cwd, text=True)
    if result.returncode != 0:
        raise LlamaBuildError(f"{label} failed with exit code {result.returncode}")


def sync_llama_source(repo_url: str, tag: str, src_dir: Path) -> None:
    """Clone or fetch the specified tag of llama.cpp into src_dir."""
    if not (src_dir / ".git").exists():
        src_dir.parent.mkdir(parents=True, exist_ok=True)
        if src_dir.exists():
            shutil.rmtree(src_dir)
        logger.info(f"Cloning {repo_url} (tag: {tag}) into {src_dir}...")
        _run_cmd(
            ["git", "clone", "--depth", "1", "--branch", tag, repo_url, str(src_dir)],
            label="git clone",
        )
    else:
        logger.info(f"Updating {src_dir} to tag: {tag}...")
        _run_cmd(["git", "remote", "set-url", "origin", repo_url], cwd=src_dir, label="git remote set-url")
        fetch_spec = f"+refs/tags/{tag}:refs/tags/{tag}"
        try:
            _run_cmd(["git", "fetch", "--depth", "1", "origin", fetch_spec], cwd=src_dir, label="git fetch")
        except LlamaBuildError:
            _run_cmd(["git", "fetch", "--depth", "1", "origin", tag], cwd=src_dir, label="git fetch fallback")
        _run_cmd(["git", "checkout", tag], cwd=src_dir, label="git checkout")


def find_built_binary(build_dir: Path) -> Path:
    """Locate the compiled llama-server executable within build_dir."""
    candidates = [
        build_dir / "bin" / "llama-server",
        build_dir / "tools" / "server" / "llama-server",
        build_dir / "llama-server",
    ]
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate

    # Recursive fallback
    for p in build_dir.glob("**/llama-server"):
        if p.is_file() and os.access(p, os.X_OK):
            return p

    raise LlamaBuildError(f"llama-server executable not found in build directory: {build_dir}")


def build_llama_server(
    repo_url: str = DEFAULT_REPO_URL,
    tag: str = DEFAULT_TAG,
    backend: str = "auto",
    minimal: bool = True,
    clean: bool = True,
    cmake_flags: list[str] | None = None,
    src_dir: Path = DEFAULT_SRC_DIR,
    bin_dir: Path = DEFAULT_BIN_DIR,
) -> Path:
    """Build the minimal, optimized llama-server binary for host execution in pa-container."""
    ok, err = check_build_prerequisites()
    if not ok:
        raise LlamaBuildError(err)

    resolved_tag = tag
    if tag.strip().lower() == "latest":
        resolved_tag = resolve_latest_tag(repo_url)

    resolved_backend = detect_hardware_backend(backend)
    logger.info(f"Targeting llama.cpp backend: {resolved_backend} (tag={resolved_tag}, minimal={minimal})")

    sync_llama_source(repo_url=repo_url, tag=resolved_tag, src_dir=src_dir)

    build_dir = src_dir / "build"
    if clean and build_dir.exists():
        logger.info(f"Cleaning build directory: {build_dir}")
        shutil.rmtree(build_dir)

    build_dir.mkdir(parents=True, exist_ok=True)
    bin_dir.mkdir(parents=True, exist_ok=True)

    flags = get_minimal_cmake_flags(
        backend=resolved_backend,
        minimal=minimal,
        extra_flags=cmake_flags,
    )
    cmake_configure_cmd = ["cmake", "-S", str(src_dir), "-B", str(build_dir), *flags]
    _run_cmd(cmake_configure_cmd, cwd=src_dir, label="cmake configure")

    num_cores = os.cpu_count() or 4
    cmake_build_cmd = [
        "cmake",
        "--build",
        str(build_dir),
        "--config",
        "Release",
        "--target",
        "llama-server",
        "-j",
        str(num_cores),
    ]
    _run_cmd(cmake_build_cmd, cwd=src_dir, label="cmake build")

    built_bin = find_built_binary(build_dir)
    target_bin = bin_dir / "llama-server"

    logger.info(f"Installing {built_bin} to {target_bin}...")
    shutil.copy2(built_bin, target_bin)
    target_bin.chmod(0o755)

    # If any Metal libraries exist alongside the binary, copy them as well
    for metal_file in built_bin.parent.glob("*.metal*"):
        shutil.copy2(metal_file, bin_dir / metal_file.name)

    # Smoke test execution
    try:
        smoke_res = subprocess.run(
            [str(target_bin), "--version"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        logger.info(
            f"llama-server installed successfully! Version:\n{smoke_res.stdout.strip() or smoke_res.stderr.strip()}"
        )
    except Exception as e:
        logger.warning(f"Installed llama-server, but smoke test exited unexpectedly: {e}")

    return target_bin
