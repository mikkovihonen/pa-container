from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

sys.dont_write_bytecode = True

from logging_driver import LogCategory, get_category_logger
from packages.builder import generate_dynamic_builder_containerfile
from packages.dependencies import resolve_package_dependencies
from packages.discovery import (
    discover_packages,
    get_package_dir,
)
from packages.manifest import PackageManifest, load_package_manifest

logger = get_category_logger(__name__, LogCategory.BUILD)

BASE_AGENT_IMAGE = "localhost/pa-container-agent-base:local"
REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@dataclass(frozen=True)
class PackageVerificationResult:
    """Outcome of an in-container package smoke test verification."""

    package: str
    command: str
    passed: bool
    duration_ms: float
    output: str
    error: str | None = None


def ensure_base_image(runtime: str = "podman") -> None:
    """Ensure the base agent runner image exists before layering packages for smoke tests."""
    check_cmd = [runtime, "image", "exists", BASE_AGENT_IMAGE]
    try:
        res = subprocess.run(check_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if res.returncode == 0:
            return
    except Exception:
        pass

    logger.info(f"Base agent image {BASE_AGENT_IMAGE} missing. Building...")
    from build import build_agent_base

    build_agent_base(runtime)


def verify_package(
    package_name: str,
    runtime: str = "podman",
    repo_root: Path | None = None,
    timeout_seconds: int = 60,
    features: list[str] | set[str] | None = None,
) -> PackageVerificationResult:
    """Execute an automated in-container smoke test for a single Agent Capability Package."""
    pkg_dir = get_package_dir(package_name, repo_root)
    manifest_file = pkg_dir / "package.yaml"
    if not manifest_file.is_file():
        return PackageVerificationResult(
            package=package_name,
            command="",
            passed=False,
            duration_ms=0.0,
            output="",
            error=f"Manifest not found: {manifest_file}",
        )

    manifest = load_package_manifest(manifest_file)
    v_cmd = manifest.verification.command.strip()
    expected_contains_list = (
        [manifest.verification.expected_output_contains] if manifest.verification.expected_output_contains else []
    )

    if not v_cmd:
        return PackageVerificationResult(
            package=package_name,
            command="",
            passed=True,
            duration_ms=0.0,
            output="No verification command defined (skipped)",
            error=None,
        )

    deps = sorted(set(manifest.runtime.dependencies))
    packages_to_ensure: dict[str, list[str]] = {dep: [] for dep in deps}
    packages_to_ensure[package_name] = []

    start_time = time.perf_counter()
    clean_name = package_name.replace("/", "-")
    temp_dir = Path(tempfile.mkdtemp(prefix=f"pa-smoke-{clean_name}-"))
    test_tag = f"localhost/pa-container-smoke-{clean_name}-{uuid.uuid4().hex[:8]}:local"

    try:
        ensure_base_image(runtime=runtime)
        resolved_test_specs = resolve_package_dependencies(packages_to_ensure, repo_root=repo_root)

        cf_content = generate_dynamic_builder_containerfile(
            resolved_test_specs,
            repo_root=repo_root,
            target="smoke",
            base_tag=BASE_AGENT_IMAGE,
        )
        cf_path = temp_dir / "Containerfile"
        cf_path.write_text(cf_content)

        # Build ephemeral test container
        build_cmd = [
            runtime,
            "build",
            "--force-rm",
            "-t",
            test_tag,
            "-f",
            str(cf_path),
            str(repo_root or REPO_ROOT),
        ]
        build_proc = subprocess.run(
            build_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=120,
        )
        if build_proc.returncode != 0:
            duration = (time.perf_counter() - start_time) * 1000
            return PackageVerificationResult(
                package=package_name,
                command=v_cmd,
                passed=False,
                duration_ms=duration,
                output=build_proc.stdout,
                error=f"Failed to assemble verification container layer (exit {build_proc.returncode})",
            )

        # Execute verification command in ephemeral container directly via /bin/sh
        run_cmd = [
            runtime,
            "run",
            "--rm",
            "--network=none",
            "--entrypoint",
            "/bin/sh",
            test_tag,
            "-c",
            v_cmd,
        ]
        run_proc = subprocess.run(
            run_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout_seconds,
        )
        duration = (time.perf_counter() - start_time) * 1000
        output = run_proc.stdout.strip()

        if run_proc.returncode != 0:
            return PackageVerificationResult(
                package=package_name,
                command=v_cmd,
                passed=False,
                duration_ms=duration,
                output=output,
                error=f"Verification command failed with exit code {run_proc.returncode}",
            )

        for expected in expected_contains_list:
            if expected not in output:
                return PackageVerificationResult(
                    package=package_name,
                    command=v_cmd,
                    passed=False,
                    duration_ms=duration,
                    output=output,
                    error=f"Expected substring '{expected}' not found in verification output",
                )

        return PackageVerificationResult(
            package=package_name,
            command=v_cmd,
            passed=True,
            duration_ms=duration,
            output=output,
            error=None,
        )

    except subprocess.TimeoutExpired:
        duration = (time.perf_counter() - start_time) * 1000
        return PackageVerificationResult(
            package=package_name,
            command=v_cmd,
            passed=False,
            duration_ms=duration,
            output="",
            error=f"Verification timed out after {timeout_seconds}s",
        )
    except Exception as e:
        duration = (time.perf_counter() - start_time) * 1000
        return PackageVerificationResult(
            package=package_name,
            command=v_cmd,
            passed=False,
            duration_ms=duration,
            output="",
            error=str(e),
        )
    finally:
        # Clean up ephemeral image
        subprocess.run(
            [runtime, "rmi", "-f", test_tag],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        shutil.rmtree(temp_dir, ignore_errors=True)


def verify_packages(
    packages: list[str] | set[str] | None = None,
    runtime: str = "podman",
    repo_root: Path | None = None,
) -> list[PackageVerificationResult]:
    """Execute smoke test verifications for a collection of packages."""
    all_discovered = discover_packages(repo_root)
    if not packages or "all" in packages:
        target_pkgs = sorted(all_discovered.keys())
    else:
        target_pkgs = sorted(p for p in packages if p in all_discovered)

    results: list[PackageVerificationResult] = []
    for pkg in target_pkgs:
        logger.info(f"Verifying package '{pkg}'...")
        res = verify_package(pkg, runtime=runtime, repo_root=repo_root)
        results.append(res)
    return results


def render_verification_results(
    results: list[PackageVerificationResult],
    title: str = "Agent Capability Package (ACP) Smoke Test Results",
) -> None:
    """Print a structured summary table of package verification results to the terminal."""
    try:
        from rich.console import Console
        from rich.table import Table

        console = Console()
        table = Table(title=title, show_lines=False)
        table.add_column("Package", style="bold cyan")
        table.add_column("Status", justify="center")
        table.add_column("Duration", justify="right")
        table.add_column("Command", style="dim")
        table.add_column("Details", style="dim")

        for r in results:
            if r.passed:
                status = "[bold green]✔ PASS[/bold green]"
                details = r.output.split("\n")[0][:45] if r.output else ""
            else:
                status = "[bold red]✗ FAIL[/bold red]"
                details = f"[red]{r.error or 'Failed'}[/red]"

            table.add_row(
                r.package,
                status,
                f"{r.duration_ms:.0f}ms",
                r.command,
                details,
            )

        console.print(table)
    except ImportError:
        # Fallback to plain text
        print(f"\n=== {title} ===")
        for r in results:
            tag = "[PASS]" if r.passed else "[FAIL]"
            err = f" - {r.error}" if r.error else ""
            print(f"  {tag} {r.package:20} ({r.duration_ms:.0f}ms): {r.command}{err}")
        print("=" * (len(title) + 8) + "\n")


def verify_package_integration(
    package_name: str,
    runtime: str = "podman",
    repo_root: Path | None = None,
) -> PackageVerificationResult:
    """Execute an automated end-to-end integration test launch for an Agent Capability Package."""
    pkg_dir = get_package_dir(package_name, repo_root)
    manifest_file = pkg_dir / "package.yaml"
    if not manifest_file.is_file():
        return PackageVerificationResult(
            package=package_name,
            command="",
            passed=False,
            duration_ms=0.0,
            output="",
            error=f"Manifest not found: {manifest_file}",
        )

    manifest = load_package_manifest(manifest_file)
    if not manifest.integration.enabled or not manifest.integration.command.strip():
        return PackageVerificationResult(
            package=package_name,
            command="",
            passed=True,
            duration_ms=0.0,
            output="No integration test defined (skipped)",
            error=None,
        )

    start_time = time.perf_counter()
    timeout_seconds = manifest.integration.timeout_seconds
    int_cmd = manifest.integration.command.strip()
    expected_output = manifest.integration.expected_output_contains

    temp_dir = Path(tempfile.mkdtemp(prefix=f"pa-int-{package_name}-"))
    test_tag = f"localhost/pa-container-int-{package_name}-{uuid.uuid4().hex[:8]}:local"

    # Write ephemeral project config
    test_proj = manifest.integration.test_project or {}
    proj_cfg = test_proj.get("config", {})
    pa_cfg_dir = temp_dir / ".pa-container"
    pa_cfg_dir.mkdir(parents=True, exist_ok=True)

    import yaml

    cfg_data = dict(proj_cfg)
    if "packages" not in cfg_data:
        cfg_data["packages"] = [package_name]
    (pa_cfg_dir / "config.yaml").write_text(yaml.dump(cfg_data))

    from images import resolve_project_packages
    from packages.dependencies import resolve_package_dependencies
    from packages.projection import aggregate_runtime_privileges

    resolved_pkgs = resolve_project_packages(temp_dir, repo_root=repo_root)
    if package_name not in resolved_pkgs:
        resolved_pkgs[package_name] = []
    resolved_pkgs = resolve_package_dependencies(resolved_pkgs, repo_root=repo_root)

    try:
        ensure_base_image(runtime=runtime)

        cf_content = generate_dynamic_builder_containerfile(
            resolved_pkgs,
            repo_root=repo_root,
            target="smoke",
            base_tag=BASE_AGENT_IMAGE,
        )
        cf_path = temp_dir / "Containerfile"
        cf_path.write_text(cf_content)

        build_cmd = [
            runtime,
            "build",
            "--force-rm",
            "-t",
            test_tag,
            "-f",
            str(cf_path),
            str(repo_root or REPO_ROOT),
        ]
        build_proc = subprocess.run(
            build_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=120,
        )
        if build_proc.returncode != 0:
            duration = (time.perf_counter() - start_time) * 1000
            return PackageVerificationResult(
                package=package_name,
                command=int_cmd,
                passed=False,
                duration_ms=duration,
                output=build_proc.stdout,
                error=f"Failed to assemble integration container layer (exit {build_proc.returncode})",
            )

        manifests_to_aggregate: list[PackageManifest] = []
        for p_name in resolved_pkgs:
            p_manifest_file = get_package_dir(p_name, repo_root) / "package.yaml"
            if p_manifest_file.is_file():
                manifests_to_aggregate.append(load_package_manifest(p_manifest_file))

        privileges = aggregate_runtime_privileges(manifests_to_aggregate)

        run_args = [
            runtime,
            "run",
            "--rm",
            "--name",
            f"pa-int-test-{uuid.uuid4().hex[:8]}",
            "--entrypoint",
            "/bin/sh",
        ]

        # Add devices
        for dev in privileges.get("devices", []):
            host_dev = dev.split(":")[0]
            if Path(host_dev).exists():
                run_args.extend(["--device", dev])

        # Add caps
        for cap in privileges.get("cap_add", []):
            run_args.extend(["--cap-add", cap])

        # Add sysctl
        for sk, sv in privileges.get("sysctl", {}).items():
            run_args.extend(["--sysctl", f"{sk}={sv}"])

        # Add shm_size
        shm_sz = privileges.get("shm_size")
        if shm_sz:
            run_args.extend(["--shm-size", shm_sz])

        # Add env
        for ek, ev in privileges.get("env", {}).items():
            run_args.extend(["--env", f"{ek}={ev}"])

        # Nested containers privileges
        if privileges.get("nested_containers"):
            if Path("/dev/fuse").exists():
                run_args.extend(["--device", "/dev/fuse"])
            if Path("/dev/net/tun").exists():
                run_args.extend(["--device", "/dev/net/tun"])
            run_args.extend(
                [
                    "--security-opt",
                    "label=disable",
                    "--security-opt",
                    "unmask=ALL",
                    "--cap-add",
                    "SYS_ADMIN",
                    "--tmpfs",
                    "/home/agent/.local/share/containers:rw,exec,suid,nodev",
                    "--tmpfs",
                    "/run/user/1000:rw,exec,suid,nodev",
                    "--env",
                    "XDG_RUNTIME_DIR=/run/user/1000",
                    "--env",
                    "PA_CONTAINER_NESTED=true",
                ]
            )

        run_cmd = [
            *run_args,
            test_tag,
            "-c",
            int_cmd,
        ]

        run_proc = subprocess.run(
            run_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout_seconds,
        )
        duration = (time.perf_counter() - start_time) * 1000
        output = run_proc.stdout.strip()

        if run_proc.returncode != 0:
            return PackageVerificationResult(
                package=package_name,
                command=int_cmd,
                passed=False,
                duration_ms=duration,
                output=output,
                error=f"Integration test command failed with exit code {run_proc.returncode}",
            )

        if expected_output and expected_output not in output:
            return PackageVerificationResult(
                package=package_name,
                command=int_cmd,
                passed=False,
                duration_ms=duration,
                output=output,
                error=f"Expected substring '{expected_output}' not found in integration test output",
            )

        return PackageVerificationResult(
            package=package_name,
            command=int_cmd,
            passed=True,
            duration_ms=duration,
            output=output,
            error=None,
        )

    except subprocess.TimeoutExpired:
        duration = (time.perf_counter() - start_time) * 1000
        return PackageVerificationResult(
            package=package_name,
            command=int_cmd,
            passed=False,
            duration_ms=duration,
            output="",
            error=f"Integration test timed out after {timeout_seconds}s",
        )
    except Exception as e:
        duration = (time.perf_counter() - start_time) * 1000
        return PackageVerificationResult(
            package=package_name,
            command=int_cmd,
            passed=False,
            duration_ms=duration,
            output="",
            error=str(e),
        )
    finally:
        subprocess.run(
            [runtime, "rmi", "-f", test_tag],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        shutil.rmtree(temp_dir, ignore_errors=True)


def verify_packages_integration(
    packages: list[str] | set[str] | None = None,
    runtime: str = "podman",
    repo_root: Path | None = None,
) -> list[PackageVerificationResult]:
    """Execute integration tests for a collection of packages."""
    all_discovered = discover_packages(repo_root)
    if not packages or "all" in packages:
        target_pkgs = sorted(all_discovered.keys())
    else:
        target_pkgs = sorted(p for p in packages if p in all_discovered)

    results: list[PackageVerificationResult] = []
    for pkg in target_pkgs:
        logger.info(f"Running integration test for package '{pkg}'...")
        res = verify_package_integration(pkg, runtime=runtime, repo_root=repo_root)
        results.append(res)
    return results
