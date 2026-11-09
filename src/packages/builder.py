from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from packages.manifest import PackageManifest

sys.dont_write_bytecode = True

from logging_driver import LogCategory, get_category_logger, get_log_driver
from packages.discovery import compute_package_hash, get_package_dir, package_to_image_tag
from packages.manifest import load_package_manifest

logger = get_category_logger(__name__, LogCategory.BUILD)

"""Build and caching orchestrator for Agent Capability Packages (ACPs)."""

FEDORA_BASE_IMAGE = "registry.fedoraproject.org/fedora-minimal:41"
REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def generate_package_containerfile(manifest: PackageManifest, package_dir: Path, repo_root: Path | None = None) -> str:
    """Generate a Containerfile to compile or stage the package into a scratch OCI image."""
    pkg_name = manifest.name
    ptype = manifest.payload.type

    lines: list[str] = [
        f"# Auto-generated build recipe for Agent Capability Package: {pkg_name} ({manifest.version})",
    ]

    if ptype == "none":
        lines.extend(
            [
                "FROM scratch",
            ]
        )
        if (package_dir / "skill" / "SKILL.md").is_file():
            lines.append(f"COPY skill/SKILL.md /usr/local/share/pa-container/packages/{pkg_name}/skill/SKILL.md")
        if (package_dir / "mcp").is_dir():
            lines.append(f"COPY mcp/ /usr/local/share/pa-container/packages/{pkg_name}/mcp/")
        return "\n".join(lines) + "\n"

    elif ptype == "binary_download":
        lines.extend(
            [
                f"FROM {FEDORA_BASE_IMAGE} AS extractor",
                "RUN microdnf install -y --nodocs curl tar gzip xz findutils shadow-utils && microdnf clean all",
                "ENV PA_STAGE=/out",
                f"WORKDIR /build/{pkg_name}",
                "COPY . /build/",
                "RUN set -euo pipefail; \\",
                "    mkdir -p /out/usr/local/bin; \\",
                '    ARCH="$(uname -m)"; \\',
            ]
        )
        # Generate platform-specific download logic
        for arch, plat in manifest.payload.platforms.items():
            arch_match = "x86_64" if arch in ("x86_64", "amd64") else "aarch64"
            lines.append(f'    if [ "$ARCH" = "{arch_match}" ]; then \\')
            lines.append(f'        curl -fsSL --retry 3 -o /tmp/pkg.tar "{plat.url}"; \\')
            lines.append(f'        echo "{plat.sha256}  /tmp/pkg.tar" | sha256sum -c -; \\')
            lines.append("        mkdir -p /tmp/extracted; \\")
            lines.append("        if tar -tf /tmp/pkg.tar >/dev/null 2>&1; then \\")
            lines.append("            tar -xf /tmp/pkg.tar -C /tmp/extracted; \\")
            lines.append("        elif unzip -t /tmp/pkg.tar >/dev/null 2>&1; then \\")
            lines.append("            unzip -q /tmp/pkg.tar -d /tmp/extracted; \\")
            lines.append("        fi; \\")
            for src_rel, dest_abs in plat.extract_map.items():
                lines.append(f'        mkdir -p "$(dirname "/out{dest_abs}")"; \\')
                lines.append(f'        cp -a "/tmp/extracted/{src_rel}" "/out{dest_abs}"; \\')
                lines.append(f'        chmod 755 "/out{dest_abs}" 2>/dev/null || true; \\')
            lines.append("        rm -rf /tmp/pkg.tar /tmp/extracted; \\")
            lines.append("    fi; \\")

        # Copy skill and MCP configs into /out
        lines.extend(
            [
                f'    mkdir -p "/out/usr/local/share/pa-container/packages/{pkg_name}/skill"; \\',
                f'    if [ -f /build/skill/SKILL.md ]; then cp -a /build/skill/SKILL.md "/out/usr/local/share/pa-container/packages/{pkg_name}/skill/"; fi; \\',
                f'    if [ -d /build/mcp ]; then cp -a /build/mcp "/out/usr/local/share/pa-container/packages/{pkg_name}/"; fi; \\',
                "    true",
                "FROM scratch",
                "COPY --from=extractor /out/ /",
            ]
        )
        return "\n".join(lines) + "\n"

    elif ptype == "build_script":
        build_deps = manifest.payload.build_deps if manifest.payload.build_deps is not None else ["gcc", "make", "git"]
        build_deps_str = (" " + " ".join(build_deps)) if build_deps else ""
        script_name = manifest.payload.script or "build.sh"
        common_script_path = (repo_root or REPO_ROOT) / "packages" / "common.sh"
        common_script = common_script_path.read_text() if common_script_path.is_file() else ""
        lines.extend(
            [
                f"FROM {FEDORA_BASE_IMAGE} AS builder",
                f"RUN microdnf install -y --nodocs bash coreutils curl git tar gzip xz unzip findutils shadow-utils libatomic libstdc++{build_deps_str} && microdnf clean all",
                "ENV PA_STAGE=/out",
                'ENV PATH="/usr/local/bin:${PATH}"',
            ]
        )
        for bp in manifest.payload.build_packages:
            lines.append(f"COPY --from={package_to_image_tag(bp)} / /")

        if common_script:
            lines.extend(
                [
                    "RUN mkdir -p /build",
                    "COPY <<'EOF_COMMON' /build/common.sh",
                    common_script.rstrip(),
                    "EOF_COMMON",
                    "ENV BASH_ENV=/build/common.sh",
                ]
            )

        for k, v in manifest.payload.env.items():
            lines.append(f'ENV {k}="{v}"')
        lines.extend(
            [
                f"WORKDIR /build/{pkg_name}",
                "COPY . /build/",
                f"RUN mkdir -p /out && bash /build/{script_name}",
                f'RUN mkdir -p "/out/usr/local/share/pa-container/packages/{pkg_name}/skill" \\',
                f' && if [ -f /build/skill/SKILL.md ]; then cp -a /build/skill/SKILL.md "/out/usr/local/share/pa-container/packages/{pkg_name}/skill/"; fi \\',
                f' && if [ -d /build/mcp ]; then cp -a /build/mcp "/out/usr/local/share/pa-container/packages/{pkg_name}/"; fi',
                "FROM scratch",
                "COPY --from=builder /out/ /",
            ]
        )
        return "\n".join(lines) + "\n"

    raise ValueError(f"Unsupported payload type '{ptype}' in package {pkg_name}")


def build_package(
    package_name: str,
    runtime: str = "podman",
    repo_root: Path | None = None,
    label: str | None = None,
) -> None:
    """Build a single Agent Capability Package into its scratch OCI image."""
    pkg_dir = get_package_dir(package_name, repo_root)
    manifest_file = pkg_dir / "package.yaml"
    if not manifest_file.is_file():
        raise FileNotFoundError(f"Package '{package_name}' missing manifest at {manifest_file}")

    manifest = load_package_manifest(manifest_file)
    pkg_hash = compute_package_hash(package_name, repo_root)
    tag = package_to_image_tag(package_name)
    build_ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Ensure build-time package dependencies are built first
    if manifest.payload.build_packages:
        for dep in manifest.payload.build_packages:
            if not package_image_is_current(dep, repo_root=repo_root, runtime=runtime):
                build_package(dep, runtime=runtime, repo_root=repo_root)

    logger.info(f"Building package '{package_name}' ({runtime}): {tag} (hash: {pkg_hash})")

    # If the package has its own Containerfile, use it directly. Otherwise generate one.
    custom_cf = pkg_dir / "Containerfile"
    temp_cf: Path | None = None
    if custom_cf.is_file():
        cf_path = custom_cf
    else:
        cf_content = generate_package_containerfile(manifest, pkg_dir, repo_root=repo_root)
        temp_dir = Path(tempfile.mkdtemp(prefix=f"pa-pkg-{package_name}-"))
        temp_cf = temp_dir / "Containerfile"
        temp_cf.write_text(cf_content)
        cf_path = temp_cf

    try:
        cmd = [
            runtime,
            "build",
            "--force-rm",
            "--label",
            f"pa-container.build.time={build_ts}",
            "--label",
            "pa-container.type=package",
            "--label",
            f"pa-container.package={package_name}",
            "--label",
            f"pa-container.hash={pkg_hash}",
            "--tag",
            tag,
            "--file",
            str(cf_path),
            str(pkg_dir),
        ]
        log_drv = get_log_driver()
        if log_drv is not None:
            log_drv.run_command_logged(cmd, category=LogCategory.BUILD)
        else:
            subprocess.run(cmd, check=True)
    finally:
        if temp_cf is not None and temp_cf.parent.is_dir():
            shutil.rmtree(temp_cf.parent, ignore_errors=True)


def package_image_is_current(
    package_name: str,
    repo_root: Path | None = None,
    runtime: str | None = None,
) -> bool:
    """Check if the local image for package_name matches current package content hash."""
    rt = runtime or "podman"
    tag = package_to_image_tag(package_name)
    inspect_cmd = [rt, "image", "inspect", tag, "--format", '{{index .Labels "pa-container.hash"}}']
    try:
        out = subprocess.check_output(inspect_cmd, stderr=subprocess.DEVNULL, text=True).strip()
    except subprocess.CalledProcessError, FileNotFoundError:
        return False

    current_hash = compute_package_hash(package_name, repo_root)
    return out == current_hash


def ensure_package_images(
    packages: list[str] | set[str],
    runtime: str = "podman",
    repo_root: Path | None = None,
) -> None:
    """Ensure that all requested packages have up-to-date OCI capability images."""
    for pkg in sorted(packages):
        if not package_image_is_current(pkg, repo_root=repo_root, runtime=runtime):
            logger.info(f"Package '{pkg}' image missing or stale. Compiling...")
            build_package(pkg, runtime=runtime, repo_root=repo_root)
