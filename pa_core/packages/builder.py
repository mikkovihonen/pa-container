from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from packages.manifest import PackageManifest

sys.dont_write_bytecode = True

from logging_driver import LogCategory, get_category_logger, get_log_driver
from packages.dependencies import resolve_package_dependencies
from packages.discovery import (
    collect_distro_packages,
    compute_package_hash,
    discover_packages,
    get_package_dir,
    package_to_content_tag,
    package_to_image_tag,
)
from packages.manifest import PlatformDownload, load_package_manifest

logger = get_category_logger(__name__, LogCategory.BUILD)

"""Dynamic builder orchestrator for Agent Capability Packages (ACPs) and agent images."""

FEDORA_BASE_IMAGE = "registry.fedoraproject.org/fedora-minimal:45"
REPO_ROOT = Path(__file__).resolve().parent.parent.parent

BASE_SYSTEM_BUILD_UTILS: list[str] = [
    "bash",
    "coreutils",
    "curl",
    "findutils",
    "git",
    "gzip",
    "libatomic",
    "libstdc++",
    "shadow-utils",
    "tar",
    "unzip",
    "xz",
]


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


def _append_binary_download(platforms: dict[str, PlatformDownload], dest_prefix: str = "/out") -> list[str]:
    lines: list[str] = [
        "RUN set -euo pipefail; \\",
        '    ARCH="$(uname -m)"; \\',
    ]
    for arch, plat in platforms.items():
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
            lines.append(f'        mkdir -p "$(dirname "{dest_prefix}{dest_abs}")"; \\')
            lines.append(f'        cp -a "/tmp/extracted/{src_rel}" "{dest_prefix}{dest_abs}"; \\')
            lines.append(f'        chmod 755 "{dest_prefix}{dest_abs}" 2>/dev/null || true; \\')
        lines.append("        rm -rf /tmp/pkg.tar /tmp/extracted; \\")
        lines.append("    fi; \\")
    lines.append("    true")
    return lines


def _append_skill_and_metadata(
    pkg_name: str,
    clean_pkg: str,
    assembled_skill: str,
    username: str,
) -> list[str]:
    dest_prefix = f"/out/{clean_pkg}"
    build_dir = f"/home/{username}/build"
    lines: list[str] = [
        f'RUN mkdir -p "{dest_prefix}/usr/local/share/pa-container/packages/{pkg_name}/skill"',
    ]
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
            f'RUN if [ -f {build_dir}/skill/SKILL.md ]; then cp -a {build_dir}/skill/SKILL.md "{dest_prefix}/usr/local/share/pa-container/packages/{pkg_name}/skill/"; fi'
        )
    lines.append(
        f'RUN if [ -f {build_dir}/package.yaml ]; then cp -a {build_dir}/package.yaml "{dest_prefix}/usr/local/share/pa-container/packages/{pkg_name}/"; fi \\'
    )
    lines.append(
        f' && if [ -d {build_dir}/mcp ]; then cp -a {build_dir}/mcp "{dest_prefix}/usr/local/share/pa-container/packages/{pkg_name}/"; fi'
    )
    lines.append(
        f"RUN if [ -d {build_dir}/entrypoint.d/root ]; then "
        f'mkdir -p "{dest_prefix}/usr/local/share/pa-container/entrypoint.d/root" && '
        f'cp -a {build_dir}/entrypoint.d/root/* "{dest_prefix}/usr/local/share/pa-container/entrypoint.d/root/" && '
        f'chmod +x "{dest_prefix}/usr/local/share/pa-container/entrypoint.d/root/"*.sh 2>/dev/null || true; fi'
    )
    lines.append(
        f"RUN if [ -d {build_dir}/entrypoint.d/agent ]; then "
        f'mkdir -p "{dest_prefix}/usr/local/share/pa-container/entrypoint.d/agent" && '
        f'cp -a {build_dir}/entrypoint.d/agent/* "{dest_prefix}/usr/local/share/pa-container/entrypoint.d/agent/" && '
        f'chmod +x "{dest_prefix}/usr/local/share/pa-container/entrypoint.d/agent/"*.sh 2>/dev/null || true; fi'
    )
    return lines


def generate_dynamic_builder_containerfile(
    resolved_specs: Mapping[str, Sequence[str] | None],
    repo_root: Path | None = None,
    manifests: dict[str, PackageManifest] | None = None,
    target: str = "agent",  # "agent", "package", "smoke"
    base_tag: str | None = None,
    export_package: str | None = None,
    root_commands_path: Path | str | None = None,
    image_labels: Mapping[str, str] | None = None,
    use_prebuilt_packages: bool = False,
) -> str:
    """Generate a multi-stage dynamic builder or composition Containerfile.

    If use_prebuilt_packages is True, generates a fast composition Containerfile
    layering pre-built OCI package images directly onto the base image.
    Otherwise, compiles artifacts inside an isolated multi-stage build.
    """
    r_root = repo_root or REPO_ROOT
    if manifests is None:
        manifests = discover_packages(r_root)

    # Fast composition from pre-built capability images
    if target in ("agent", "smoke") and use_prebuilt_packages:
        lines: list[str] = [
            f"# Auto-generated composition recipe by pa-container ({target})",
            f"FROM {base_tag or FEDORA_BASE_IMAGE}",
        ]
        distro_pkgs = collect_distro_packages(resolved_specs, manifests=manifests, repo_root=r_root)
        if distro_pkgs:
            lines.append(f"RUN microdnf install -y --nodocs {' '.join(distro_pkgs)} && microdnf clean all")

        for pkg in resolved_specs:
            clean_p = pkg.lower().replace("_", "-")
            active_feats = sorted(resolved_specs[pkg] or [])
            pkg_hash = compute_package_hash(pkg, repo_root=r_root, features=active_feats)
            content_tag = package_to_content_tag(pkg, pkg_hash, features=active_feats)
            lines.append(f"COPY --from={content_tag} / /")

        if target == "agent":
            if root_commands_path:
                rc_path = Path(root_commands_path)
                lines.extend(
                    [
                        f"COPY --from=root_commands_path {rc_path.name} /root/commands.sh",
                        "RUN chmod +x /root/commands.sh && /root/commands.sh",
                    ]
                )
            lines.append("WORKDIR /workspace")
            if image_labels:
                for k, v in sorted(image_labels.items()):
                    lines.append(f'LABEL {k}="{v}"')
            lines.append('ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]')

        return "\n".join(lines) + "\n"

    # 1. Collect union of all system build dependencies and distro packages
    all_system_pkgs: set[str] = set(BASE_SYSTEM_BUILD_UTILS)
    for pkg_name, feats in resolved_specs.items():
        mf = manifests.get(pkg_name)
        if mf is None:
            continue
        filter_feats = set(feats or [])
        if mf.payload.build_deps:
            all_system_pkgs.update(mf.payload.build_deps)
        if mf.payload.packages:
            all_system_pkgs.update(mf.payload.packages)
        for feat_name, f_obj in mf.features.items():
            if feat_name in filter_feats or (not filter_feats and f_obj.default):
                if f_obj.payload.build_deps:
                    all_system_pkgs.update(f_obj.payload.build_deps)
                if f_obj.payload.packages:
                    all_system_pkgs.update(f_obj.payload.packages)

    system_pkgs_str = " ".join(sorted(all_system_pkgs))
    common_script_path = r_root / "pa_packages" / "common.sh"
    common_script = common_script_path.read_text().rstrip() if common_script_path.is_file() else ""

    lines: list[str] = [
        "# Auto-generated dynamic multi-stage build recipe by pa-container",
        f"FROM {FEDORA_BASE_IMAGE} AS builder-base",
        f"RUN microdnf install -y --nodocs {system_pkgs_str} && microdnf clean all",
    ]
    if common_script:
        lines.extend(
            [
                "RUN mkdir -p /usr/local/share/pa-container",
                "COPY <<'EOF_COMMON' /usr/local/share/pa-container/common.sh",
                common_script,
                "EOF_COMMON",
                "ENV BASH_ENV=/usr/local/share/pa-container/common.sh",
            ]
        )

    # 2. Emit isolated artifact build stages (in topological order)
    for pkg_name, feats in resolved_specs.items():
        clean_pkg = pkg_name.lower().replace("_", "-")
        stage_name = f"artifact-{clean_pkg}"
        username = f"builder-{clean_pkg}"
        active_feats = sorted(feats or [])
        mf = manifests.get(pkg_name)
        if mf is None:
            continue

        active_feat_configs = [mf.features[f] for f in active_feats if f in mf.features]
        pkg_dir = get_package_dir(pkg_name, r_root)

        lines.extend(
            [
                f"\n# ── Artifact: {pkg_name} ───────────────────────────────────────",
                f"FROM builder-base AS {stage_name}",
            ]
        )

        # Dynamic build tools injection: import any declared build_packages from upstream artifact stages
        pkg_build_pkgs: list[str] = list(mf.payload.build_packages)
        for f in active_feat_configs:
            for bp in f.payload.build_packages:
                if bp not in pkg_build_pkgs:
                    pkg_build_pkgs.append(bp)

        for bp in pkg_build_pkgs:
            clean_bp = bp.lower().replace("_", "-")
            lines.append(f"COPY --from=artifact-{clean_bp} /out/{clean_bp}/ /")

        # Setup dedicated unprivileged user and stage directory
        lines.append(
            f"RUN useradd -m -s /bin/bash {username} && "
            f"mkdir -p /out/{clean_pkg} && "
            f"chown -R {username}:{username} /out/{clean_pkg} && "
            f"chmod 0750 /out/{clean_pkg}"
        )

        # Package files
        has_container = (pkg_dir / "container").is_dir() if pkg_dir.is_dir() else False
        if pkg_dir.is_dir():
            try:
                rel_pkg = str(pkg_dir.relative_to(r_root))
            except ValueError:
                rel_pkg = str(pkg_dir)

            if has_container:
                lines.append(f"COPY --chown={username}:{username} {rel_pkg}/container/ /home/{username}/build/")
                lines.append(f"COPY --chown={username}:{username} {rel_pkg}/package.yaml /home/{username}/build/")
                if (pkg_dir / "features").is_dir():
                    lines.append(
                        f"COPY --chown={username}:{username} {rel_pkg}/features/ /home/{username}/build/features/"
                    )
                if (pkg_dir / "skill").is_dir() and not (pkg_dir / "container" / "skill").is_dir():
                    lines.append(f"COPY --chown={username}:{username} {rel_pkg}/skill/ /home/{username}/build/skill/")
            else:
                lines.append(f"COPY --chown={username}:{username} {rel_pkg}/ /home/{username}/build/")
        else:
            lines.append(f"RUN mkdir -p /home/{username}/build")

        # Environment
        merged_env = dict(mf.payload.env)
        for f in active_feat_configs:
            merged_env.update(f.payload.env)
        for k, v in merged_env.items():
            lines.append(f'ENV {k}="{v}"')

        lines.extend(
            [
                f"ENV PA_STAGE=/out/{clean_pkg}",
                'ENV PATH="/usr/local/bin:${PATH}"',
                f"ENV HOME=/home/{username}",
                f"ENV TMPDIR=/tmp/{username}",
                f"USER {username}",
                f"WORKDIR /home/{username}/build",
                f"RUN mkdir -p /tmp/{username}",
            ]
        )

        ptype = mf.payload.type
        script_name = mf.payload.script or "build.sh"
        clean_script_name = script_name.removeprefix("container/") if has_container else script_name

        if ptype == "build_script":
            lines.append(f"RUN bash /home/{username}/build/{clean_script_name}")
        elif ptype == "binary_download" and mf.payload.platforms:
            lines.extend(_append_binary_download(mf.payload.platforms, dest_prefix=f"/out/{clean_pkg}"))

        for f in active_feat_configs:
            if f.payload.type == "build_script" and f.payload.script:
                clean_f_script = f.payload.script.removeprefix("container/")
                lines.append(f"RUN bash /home/{username}/build/{clean_f_script}")
            elif f.payload.type == "binary_download" and f.payload.platforms:
                lines.extend(_append_binary_download(f.payload.platforms, dest_prefix=f"/out/{clean_pkg}"))

        assembled_skill = assemble_package_skill(pkg_dir, active_feats, manifest=mf)
        lines.extend(_append_skill_and_metadata(pkg_name, clean_pkg, assembled_skill, username))

    # 3. Final Stage Assembly
    if target == "package":
        exp_pkg = export_package or (list(resolved_specs.keys())[-1] if resolved_specs else "pkg")
        clean_exp = exp_pkg.lower().replace("_", "-")
        lines.extend(
            [
                "\n# ── Scratch Export Stage ───────────────────────────────────────────",
                "FROM scratch",
                f"COPY --from=artifact-{clean_exp} /out/{clean_exp}/ /",
            ]
        )
    elif target in ("agent", "smoke"):
        lines.extend(
            [
                f"\n# ── Final Runner Stage ({target}) ────────────────────────────────",
                f"FROM {base_tag or FEDORA_BASE_IMAGE}",
            ]
        )
        distro_pkgs = collect_distro_packages(resolved_specs, manifests=manifests, repo_root=r_root)
        if distro_pkgs:
            lines.append(f"RUN microdnf install -y --nodocs {' '.join(distro_pkgs)} && microdnf clean all")

        for pkg in resolved_specs:
            clean_p = pkg.lower().replace("_", "-")
            lines.append(f"COPY --from=artifact-{clean_p} /out/{clean_p}/ /")

        if target == "agent":
            if root_commands_path:
                rc_path = Path(root_commands_path)
                lines.extend(
                    [
                        f"COPY --from=root_commands_path {rc_path.name} /root/commands.sh",
                        "RUN chmod +x /root/commands.sh && /root/commands.sh",
                    ]
                )
            lines.append("WORKDIR /workspace")
            if image_labels:
                for k, v in sorted(image_labels.items()):
                    lines.append(f'LABEL {k}="{v}"')
            lines.append('ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]')

    return "\n".join(lines) + "\n"


def generate_package_containerfile(
    manifest: PackageManifest,
    package_dir: Path,
    repo_root: Path | None = None,
    active_features: list[str] | set[str] | None = None,
) -> str:
    """Generate a Containerfile to compile or stage the package into a scratch OCI image."""
    r_root = repo_root or REPO_ROOT
    active_feats = sorted(active_features) if active_features else []
    manifests = {manifest.name: manifest}
    return generate_dynamic_builder_containerfile(
        {manifest.name: active_feats},
        repo_root=r_root,
        manifests=manifests,
        target="package",
        export_package=manifest.name,
    )


def build_package(
    package_name: str,
    runtime: str = "podman",
    repo_root: Path | None = None,
    label: str | None = None,
    features: list[str] | set[str] | None = None,
) -> None:
    """Build a single Agent Capability Package into its scratch OCI image."""
    r_root = repo_root or REPO_ROOT
    pkg_dir = get_package_dir(package_name, r_root)
    manifest_file = pkg_dir / "package.yaml"
    if not manifest_file.is_file():
        raise FileNotFoundError(f"Package '{package_name}' missing manifest at {manifest_file}")

    load_package_manifest(manifest_file)
    active_feats = sorted(features) if features else []
    pkg_hash = compute_package_hash(package_name, r_root, features=active_feats)
    tag = package_to_image_tag(package_name, features=active_feats)
    build_ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    resolved_specs = resolve_package_dependencies({package_name: active_feats}, repo_root=r_root)

    feat_desc = f" (features: {active_feats})" if active_feats else ""
    logger.info(f"Building package '{package_name}'{feat_desc} ({runtime}): {tag} (hash: {pkg_hash})")

    cf_content = generate_dynamic_builder_containerfile(
        resolved_specs,
        repo_root=r_root,
        target="package",
        export_package=package_name,
    )
    temp_dir = Path(tempfile.mkdtemp(prefix=f"pa-pkg-{package_name}-"))
    temp_cf = temp_dir / "Containerfile"
    temp_cf.write_text(cf_content)

    content_tag = package_to_content_tag(package_name, pkg_hash, features=active_feats)

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
            "--tag",
            content_tag,
            "--file",
            str(temp_cf),
            str(r_root),
        ]
        log_drv = get_log_driver()
        if log_drv is not None:
            log_drv.run_command_logged(cmd, category=LogCategory.BUILD)
        else:
            subprocess.run(cmd, check=True)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def package_image_is_current(
    package_name: str,
    repo_root: Path | None = None,
    runtime: str | None = None,
    features: list[str] | set[str] | None = None,
) -> bool:
    """Check if the local image for package_name (with active features) matches current content hash."""
    rt = runtime or "podman"
    active_feats = sorted(features) if features else []
    current_hash = compute_package_hash(package_name, repo_root, features=active_feats)
    content_tag = package_to_content_tag(package_name, current_hash, features=active_feats)

    # 1. Fast existence check on immutable content-addressed tag
    try:
        exists_cmd = [rt, "image", "exists", content_tag]
        res = subprocess.run(exists_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        if res.returncode == 0:
            return True
    except subprocess.SubprocessError, FileNotFoundError:
        pass

    # 2. Fallback check on semantic local tag via pa-container.hash label
    tag = package_to_image_tag(package_name, features=active_feats)
    inspect_cmd = [rt, "image", "inspect", tag, "--format", '{{index .Labels "pa-container.hash"}}']
    try:
        out = subprocess.check_output(inspect_cmd, stderr=subprocess.DEVNULL, text=True).strip()
    except subprocess.CalledProcessError, FileNotFoundError:
        return False

    return out == current_hash


def ensure_package_images(
    packages: list[str] | set[str] | dict[str, list[str]],
    runtime: str = "podman",
    repo_root: Path | None = None,
    max_workers: int | None = None,
) -> None:
    """Ensure that all requested packages have up-to-date OCI capability images, building missing packages in parallel."""
    import concurrent.futures
    import os

    r_root = repo_root or REPO_ROOT
    items_map: dict[str, list[str]] = (
        {pkg: sorted(feats or []) for pkg, feats in packages.items()}
        if isinstance(packages, dict)
        else {pkg: [] for pkg in sorted(packages)}
    )

    # 1. Identify missing or stale packages
    missing: dict[str, list[str]] = {}
    for pkg, feats in sorted(items_map.items()):
        if not package_image_is_current(pkg, repo_root=r_root, runtime=runtime, features=feats):
            missing[pkg] = feats

    if not missing:
        return

    # 2. Resolve dependency order across missing packages
    from packages.dependencies import resolve_package_dependencies

    resolved_missing = resolve_package_dependencies(missing, repo_root=r_root)
    manifests = discover_packages(r_root)

    # Check build memory preflight if enabled
    try:
        from build import check_build_memory

        check_build_memory(runtime, packages=resolved_missing, fatal=True)
    except Exception as e:
        logger.debug(f"Preflight memory check skipped or failed: {e}")

    # Track packages whose builds are completed/current
    completed: set[str] = {
        pkg
        for pkg in manifests
        if pkg not in resolved_missing
        or package_image_is_current(pkg, repo_root=r_root, runtime=runtime, features=resolved_missing.get(pkg, []))
    }

    workers = max_workers or min(4, max(1, os.cpu_count() or 1))
    if len(resolved_missing) <= 1 or workers <= 1:
        # Sequential execution
        for pkg, feats in resolved_missing.items():
            feat_desc = f" (features: {feats})" if feats else ""
            logger.info(f"Package '{pkg}'{feat_desc} image missing or stale. Compiling...")
            build_package(pkg, runtime=runtime, repo_root=r_root, features=feats)
        return

    # Parallel DAG-aware execution
    to_build = dict(resolved_missing)
    in_flight: dict[concurrent.futures.Future[None], str] = {}
    errors: list[tuple[str, Exception]] = []

    def _can_build(pkg_name: str, active_feats: list[str]) -> bool:
        mf = manifests.get(pkg_name)
        if not mf:
            return True
        needed_build_pkgs: set[str] = set(mf.payload.build_packages)
        for f in active_feats:
            if f in mf.features:
                needed_build_pkgs.update(mf.features[f].payload.build_packages)
        return needed_build_pkgs.issubset(completed)

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        while to_build or in_flight:
            ready = [pkg for pkg, feats in list(to_build.items()) if _can_build(pkg, feats)]
            for pkg in ready:
                feats = to_build.pop(pkg)
                feat_desc = f" (features: {feats})" if feats else ""
                logger.info(f"Package '{pkg}'{feat_desc} image missing or stale. Compiling in parallel...")
                fut = executor.submit(build_package, pkg, runtime=runtime, repo_root=r_root, features=feats)
                in_flight[fut] = pkg

            if not in_flight:
                if to_build:
                    # Circular or unsatisfied dependency fallback
                    pkg, feats = to_build.popitem()
                    build_package(pkg, runtime=runtime, repo_root=r_root, features=feats)
                    completed.add(pkg)
                    continue
                break

            done, _ = concurrent.futures.wait(in_flight.keys(), return_when=concurrent.futures.FIRST_COMPLETED)
            for fut in done:
                pkg_done = in_flight.pop(fut)
                try:
                    fut.result()
                    completed.add(pkg_done)
                except Exception as exc:
                    logger.error(f"Failed to build package '{pkg_done}': {exc}")
                    errors.append((pkg_done, exc))

            if errors:
                for f in in_flight:
                    f.cancel()
                first_pkg, first_err = errors[0]
                raise RuntimeError(f"Package build failed for '{first_pkg}': {first_err}") from first_err
