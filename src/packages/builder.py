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

FEDORA_BASE_IMAGE = "registry.fedoraproject.org/fedora-minimal:45"
REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def assemble_package_skill(
    package_dir: Path,
    active_features: list[str] | set[str] | None = None,
    manifest: PackageManifest | None = None,
) -> str:
    """Dynamically assemble a package SKILL.md from skill/base.md and active feature fragments."""
    container_dir = package_dir / "container"
    skill_dir = (container_dir / "skill") if (container_dir / "skill").is_dir() else (package_dir / "skill")
    base_file = skill_dir / "base.md"
    skill_file = skill_dir / "SKILL.md"

    base_content = ""
    if base_file.is_file():
        base_content = base_file.read_text().rstrip()
    elif skill_file.is_file():
        base_content = skill_file.read_text().rstrip()

    if not active_features:
        return base_content

    fragments: list[str] = [base_content] if base_content else []

    if manifest is None:
        mf = package_dir / "package.yaml"
        if mf.is_file():
            try:
                manifest = load_package_manifest(mf)
            except Exception:
                manifest = None

    for feat in sorted(active_features):
        frag_path: Path | None = None
        if manifest and feat in manifest.features:
            s_frag = manifest.features[feat].skill_fragment
            if s_frag:
                custom_frag = package_dir / s_frag
                if not custom_frag.is_file() and (container_dir / s_frag).is_file():
                    custom_frag = container_dir / s_frag
                if custom_frag.is_file():
                    frag_path = custom_frag
        if frag_path is None:
            default_frag = skill_dir / "features" / f"{feat}.md"
            if default_frag.is_file():
                frag_path = default_frag

        if frag_path and frag_path.is_file():
            content = frag_path.read_text().strip()
            if content:
                fragments.append(content)

    return ("\n\n---\n\n".join(fragments) + "\n") if fragments else ""


def generate_package_containerfile(
    manifest: PackageManifest,
    package_dir: Path,
    repo_root: Path | None = None,
    active_features: list[str] | set[str] | None = None,
) -> str:
    """Generate a Containerfile to compile or stage the package into a scratch OCI image."""
    pkg_name = manifest.name
    ptype = manifest.payload.type
    active_feats = sorted(active_features) if active_features else []

    lines: list[str] = [
        f"# Auto-generated build recipe for Agent Capability Package: {pkg_name} ({manifest.version})",
    ]

    # Dynamic skill assembly
    assembled_skill = assemble_package_skill(package_dir, active_feats, manifest=manifest)

    script_name = manifest.payload.script or "build.sh"
    has_container = (package_dir / "container").is_dir()
    copy_lines = ["COPY container/ /build/", "COPY package.yaml /build/"] if has_container else ["COPY . /build/"]
    clean_script_name = script_name.removeprefix("container/") if has_container else script_name

    def _append_skill_and_metadata(builder_stage: bool = True) -> None:
        dest_prefix = "/out" if builder_stage else ""
        lines.append(f'RUN mkdir -p "{dest_prefix}/usr/local/share/pa-container/packages/{pkg_name}/skill"')
        if assembled_skill:
            lines.extend(
                [
                    f"COPY <<'EOF_ACP_SKILL' {dest_prefix}/usr/local/share/pa-container/packages/{pkg_name}/skill/SKILL.md",
                    assembled_skill.rstrip(),
                    "EOF_ACP_SKILL",
                ]
            )
        else:
            lines.append(
                f'RUN if [ -f /build/skill/SKILL.md ]; then cp -a /build/skill/SKILL.md "{dest_prefix}/usr/local/share/pa-container/packages/{pkg_name}/skill/"; fi'
            )
        lines.append(
            f'RUN if [ -f /build/package.yaml ]; then cp -a /build/package.yaml "{dest_prefix}/usr/local/share/pa-container/packages/{pkg_name}/"; fi \\'
        )
        lines.append(
            f' && if [ -d /build/mcp ]; then cp -a /build/mcp "{dest_prefix}/usr/local/share/pa-container/packages/{pkg_name}/"; fi'
        )

    if ptype in ("none", "distro_package"):
        lines.extend(
            [
                f"FROM {FEDORA_BASE_IMAGE} AS assembler",
                "ENV PA_STAGE=/out",
                "WORKDIR /build",
                *copy_lines,
            ]
        )
        # Execute active feature payloads
        for feat_name in active_feats:
            if feat_name in manifest.features:
                f = manifest.features[feat_name]
                if f.payload.type == "build_script" and f.payload.script:
                    lines.append(f"RUN mkdir -p /out && bash /build/{f.payload.script}")
                elif f.payload.type == "binary_download" and f.payload.platforms:
                    lines.append("RUN set -euo pipefail; \\")
                    lines.append('    ARCH="$(uname -m)"; \\')
                    for f_arch, f_plat in f.payload.platforms.items():
                        f_arch_match = "x86_64" if f_arch in ("x86_64", "amd64") else "aarch64"
                        lines.append(f'    if [ "$ARCH" = "{f_arch_match}" ]; then \\')
                        lines.append(f'        curl -fsSL --retry 3 -o /tmp/pkg.tar "{f_plat.url}"; \\')
                        lines.append(f'        echo "{f_plat.sha256}  /tmp/pkg.tar" | sha256sum -c -; \\')
                        lines.append("        mkdir -p /tmp/extracted; \\")
                        lines.append("        if tar -tf /tmp/pkg.tar >/dev/null 2>&1; then \\")
                        lines.append("            tar -xf /tmp/pkg.tar -C /tmp/extracted; \\")
                        lines.append("        elif unzip -t /tmp/pkg.tar >/dev/null 2>&1; then \\")
                        lines.append("            unzip -q /tmp/pkg.tar -d /tmp/extracted; \\")
                        lines.append("        fi; \\")
                        for src_rel, dest_abs in f_plat.extract_map.items():
                            lines.append(f'        mkdir -p "$(dirname "/out{dest_abs}")"; \\')
                            lines.append(f'        cp -a "/tmp/extracted/{src_rel}" "/out{dest_abs}"; \\')
                            lines.append(f'        chmod 755 "/out{dest_abs}" 2>/dev/null || true; \\')
                        lines.append("        rm -rf /tmp/pkg.tar /tmp/extracted; \\")
                        lines.append("    fi; \\")
                    lines.append("    true")
        _append_skill_and_metadata(builder_stage=True)
        lines.extend(
            [
                "FROM scratch",
                "COPY --from=assembler /out/ /",
            ]
        )
        return "\n".join(lines) + "\n"

    elif ptype == "binary_download":
        lines.extend(
            [
                f"FROM {FEDORA_BASE_IMAGE} AS extractor",
                "RUN microdnf install -y --nodocs curl tar gzip xz findutils shadow-utils && microdnf clean all",
                "ENV PA_STAGE=/out",
                "WORKDIR /build",
                *copy_lines,
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
        lines.append("    true")

        # Feature payloads in binary_download
        for feat_name in active_feats:
            if feat_name in manifest.features:
                f = manifest.features[feat_name]
                if f.payload.type == "build_script" and f.payload.script:
                    lines.append(f"RUN mkdir -p /out && bash /build/{f.payload.script}")
                elif f.payload.type == "binary_download" and f.payload.platforms:
                    lines.append("RUN set -euo pipefail; \\")
                    lines.append('    ARCH="$(uname -m)"; \\')
                    for f_arch, f_plat in f.payload.platforms.items():
                        f_arch_match = "x86_64" if f_arch in ("x86_64", "amd64") else "aarch64"
                        lines.append(f'    if [ "$ARCH" = "{f_arch_match}" ]; then \\')
                        lines.append(f'        curl -fsSL --retry 3 -o /tmp/pkg.tar "{f_plat.url}"; \\')
                        lines.append(f'        echo "{f_plat.sha256}  /tmp/pkg.tar" | sha256sum -c -; \\')
                        lines.append("        mkdir -p /tmp/extracted; \\")
                        lines.append("        if tar -tf /tmp/pkg.tar >/dev/null 2>&1; then \\")
                        lines.append("            tar -xf /tmp/pkg.tar -C /tmp/extracted; \\")
                        lines.append("        elif unzip -t /tmp/pkg.tar >/dev/null 2>&1; then \\")
                        lines.append("            unzip -q /tmp/pkg.tar -d /tmp/extracted; \\")
                        lines.append("        fi; \\")
                        for src_rel, dest_abs in f_plat.extract_map.items():
                            lines.append(f'        mkdir -p "$(dirname "/out{dest_abs}")"; \\')
                            lines.append(f'        cp -a "/tmp/extracted/{src_rel}" "/out{dest_abs}"; \\')
                            lines.append(f'        chmod 755 "/out{dest_abs}" 2>/dev/null || true; \\')
                        lines.append("        rm -rf /tmp/pkg.tar /tmp/extracted; \\")
                        lines.append("    fi; \\")
                    lines.append("    true")

        _append_skill_and_metadata(builder_stage=True)
        lines.extend(
            [
                "FROM scratch",
                "COPY --from=extractor /out/ /",
            ]
        )
        return "\n".join(lines) + "\n"

    elif ptype == "build_script":
        build_deps_set = set(
            manifest.payload.build_deps if manifest.payload.build_deps is not None else ["gcc", "make", "git"]
        )
        build_pkgs_set = list(manifest.payload.build_packages)

        for feat_name in active_feats:
            if feat_name in manifest.features:
                f = manifest.features[feat_name]
                build_deps_set.update(f.payload.build_deps)
                for bp in f.payload.build_packages:
                    if bp not in build_pkgs_set:
                        build_pkgs_set.append(bp)

        build_deps_str = (" " + " ".join(sorted(build_deps_set))) if build_deps_set else ""
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
        for bp in build_pkgs_set:
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

        # Merge env
        merged_env = dict(manifest.payload.env)
        for feat_name in active_feats:
            if feat_name in manifest.features:
                merged_env.update(manifest.features[feat_name].payload.env)

        for k, v in merged_env.items():
            lines.append(f'ENV {k}="{v}"')

        lines.extend(
            [
                "WORKDIR /build",
                *copy_lines,
                f"RUN mkdir -p /out && bash /build/{clean_script_name}",
            ]
        )

        # Execute active feature payloads
        for feat_name in active_feats:
            if feat_name in manifest.features:
                f = manifest.features[feat_name]
                if f.payload.type == "build_script" and f.payload.script:
                    lines.append(f"RUN mkdir -p /out && bash /build/{f.payload.script}")
                elif f.payload.type == "binary_download" and f.payload.platforms:
                    lines.append("RUN set -euo pipefail; \\")
                    lines.append('    ARCH="$(uname -m)"; \\')
                    for f_arch, f_plat in f.payload.platforms.items():
                        f_arch_match = "x86_64" if f_arch in ("x86_64", "amd64") else "aarch64"
                        lines.append(f'    if [ "$ARCH" = "{f_arch_match}" ]; then \\')
                        lines.append(f'        curl -fsSL --retry 3 -o /tmp/pkg.tar "{f_plat.url}"; \\')
                        lines.append(f'        echo "{f_plat.sha256}  /tmp/pkg.tar" | sha256sum -c -; \\')
                        lines.append("        mkdir -p /tmp/extracted; \\")
                        lines.append("        if tar -tf /tmp/pkg.tar >/dev/null 2>&1; then \\")
                        lines.append("            tar -xf /tmp/pkg.tar -C /tmp/extracted; \\")
                        lines.append("        elif unzip -t /tmp/pkg.tar >/dev/null 2>&1; then \\")
                        lines.append("            unzip -q /tmp/pkg.tar -d /tmp/extracted; \\")
                        lines.append("        fi; \\")
                        for src_rel, dest_abs in f_plat.extract_map.items():
                            lines.append(f'        mkdir -p "$(dirname "/out{dest_abs}")"; \\')
                            lines.append(f'        cp -a "/tmp/extracted/{src_rel}" "/out{dest_abs}"; \\')
                            lines.append(f'        chmod 755 "/out{dest_abs}" 2>/dev/null || true; \\')
                        lines.append("        rm -rf /tmp/pkg.tar /tmp/extracted; \\")
                        lines.append("    fi; \\")
                    lines.append("    true")

        _append_skill_and_metadata(builder_stage=True)
        lines.extend(
            [
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
    features: list[str] | set[str] | None = None,
) -> None:
    """Build a single Agent Capability Package into its scratch OCI image."""
    pkg_dir = get_package_dir(package_name, repo_root)
    manifest_file = pkg_dir / "package.yaml"
    if not manifest_file.is_file():
        raise FileNotFoundError(f"Package '{package_name}' missing manifest at {manifest_file}")

    manifest = load_package_manifest(manifest_file)
    active_feats = sorted(features) if features else []
    pkg_hash = compute_package_hash(package_name, repo_root, features=active_feats)
    tag = package_to_image_tag(package_name, features=active_feats)
    build_ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Collect build-time package dependencies across core and features
    all_build_pkgs = list(manifest.payload.build_packages)
    for feat_name in active_feats:
        if feat_name in manifest.features:
            all_build_pkgs.extend(manifest.features[feat_name].payload.build_packages)

    for dep in all_build_pkgs:
        if not package_image_is_current(dep, repo_root=repo_root, runtime=runtime):
            build_package(dep, runtime=runtime, repo_root=repo_root)

    feat_desc = f" (features: {active_feats})" if active_feats else ""
    logger.info(f"Building package '{package_name}'{feat_desc} ({runtime}): {tag} (hash: {pkg_hash})")

    # If the package has its own Containerfile and no extra features, use it directly. Otherwise generate one.
    custom_cf = pkg_dir / "Containerfile"
    temp_cf: Path | None = None
    if custom_cf.is_file() and not active_feats:
        cf_path = custom_cf
    else:
        cf_content = generate_package_containerfile(
            manifest, pkg_dir, repo_root=repo_root, active_features=active_feats
        )
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
    features: list[str] | set[str] | None = None,
) -> bool:
    """Check if the local image for package_name (with active features) matches current content hash."""
    rt = runtime or "podman"
    active_feats = sorted(features) if features else []
    tag = package_to_image_tag(package_name, features=active_feats)
    inspect_cmd = [rt, "image", "inspect", tag, "--format", '{{index .Labels "pa-container.hash"}}']
    try:
        out = subprocess.check_output(inspect_cmd, stderr=subprocess.DEVNULL, text=True).strip()
    except subprocess.CalledProcessError, FileNotFoundError:
        return False

    current_hash = compute_package_hash(package_name, repo_root, features=active_feats)
    return out == current_hash


def ensure_package_images(
    packages: list[str] | set[str] | dict[str, list[str]],
    runtime: str = "podman",
    repo_root: Path | None = None,
) -> None:
    """Ensure that all requested packages have up-to-date OCI capability images."""
    items = sorted(packages.items()) if isinstance(packages, dict) else [(pkg, []) for pkg in sorted(packages)]

    for pkg, feats in items:
        if not package_image_is_current(pkg, repo_root=repo_root, runtime=runtime, features=feats):
            feat_desc = f" (features: {feats})" if feats else ""
            logger.info(f"Package '{pkg}'{feat_desc} image missing or stale. Compiling...")
            build_package(pkg, runtime=runtime, repo_root=repo_root, features=feats)
