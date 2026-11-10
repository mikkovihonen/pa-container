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
from packages.builder import ensure_package_images
from packages.discovery import discover_packages, get_package_dir, package_to_image_tag
from packages.manifest import load_package_manifest

logger = get_category_logger(__name__, LogCategory.BUILD)

BASE_AGENT_IMAGE = "localhost/pa-container-agent-base:local"


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

    build_agent_base(runtime, with_desktop=False)


def verify_package(
    package_name: str,
    runtime: str = "podman",
    repo_root: Path | None = None,
    timeout_seconds: int = 60,
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
    if not v_cmd:
        return PackageVerificationResult(
            package=package_name,
            command="",
            passed=True,
            duration_ms=0.0,
            output="No verification command defined (skipped)",
            error=None,
        )

    expected_contains = manifest.verification.expected_output_contains

    # Resolve required runtime packages (e.g. node, python) and target package
    deps = list(manifest.runtime.dependencies)
    all_required_pkgs = set(deps) | {package_name}

    start_time = time.perf_counter()
    temp_dir = Path(tempfile.mkdtemp(prefix=f"pa-smoke-{package_name}-"))
    test_tag = f"localhost/pa-container-smoke-{package_name}-{uuid.uuid4().hex[:8]}:local"

    try:
        ensure_base_image(runtime=runtime)
        ensure_package_images(all_required_pkgs, runtime=runtime, repo_root=repo_root)

        # Assemble ephemeral Containerfile layering base + runtime dependencies + target package
        cf_lines = [f"FROM {BASE_AGENT_IMAGE}"]
        for dep in deps:
            dep_tag = package_to_image_tag(dep)
            cf_lines.append(f"COPY --from={dep_tag} / /")

        target_tag = package_to_image_tag(package_name)
        cf_lines.append(f"COPY --from={target_tag} / /")

        cf_path = temp_dir / "Containerfile"
        cf_path.write_text("\n".join(cf_lines) + "\n")

        # Build ephemeral test container
        build_cmd = [
            runtime,
            "build",
            "--force-rm",
            "-t",
            test_tag,
            "-f",
            str(cf_path),
            str(temp_dir),
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

        if expected_contains and expected_contains not in output:
            return PackageVerificationResult(
                package=package_name,
                command=v_cmd,
                passed=False,
                duration_ms=duration,
                output=output,
                error=f"Expected substring '{expected_contains}' not found in verification output",
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


def render_verification_results(results: list[PackageVerificationResult]) -> None:
    """Print a structured summary table of package verification results to the terminal."""
    try:
        from rich.console import Console
        from rich.table import Table

        console = Console()
        table = Table(title="Agent Capability Package (ACP) Smoke Test Results", show_lines=False)
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
        print("\n=== Agent Capability Package (ACP) Smoke Test Results ===")
        for r in results:
            tag = "[PASS]" if r.passed else "[FAIL]"
            err = f" - {r.error}" if r.error else ""
            print(f"  {tag} {r.package:20} ({r.duration_ms:.0f}ms): {r.command}{err}")
        print("========================================================\n")
