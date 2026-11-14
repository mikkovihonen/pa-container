from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

sys.dont_write_bytecode = True

from packages import (
    aggregate_egress_hosts,
    aggregate_runtime_privileges,
    aggregate_token_replacers,
    assemble_package_skill,
    collect_distro_packages,
    compute_package_hash,
    discover_packages,
    get_mcp_servers_dict,
    get_package_dir,
    package_to_image_tag,
    parse_package_manifest,
    resolve_package_dependencies,
)
from packages.builder import generate_package_containerfile


def test_discover_packages():
    pkgs = discover_packages()
    assert len(pkgs) >= 20
    assert "podman" in pkgs
    assert "languages" in pkgs
    assert "languages/python" in pkgs
    assert "languages/node" in pkgs
    assert "languages/rust" in pkgs
    assert "source-control" in pkgs
    assert "code-intelligence" in pkgs
    assert "virtual-desktop" in pkgs

    podman = pkgs["podman"]
    assert podman.name == "podman"
    assert podman.payload.type == "build_script"
    assert podman.skill.enabled is True
    assert podman.mcp.enabled is True
    assert podman.runtime.nested_containers is True


def test_package_image_tag():
    assert package_to_image_tag("podman") == "pa-container-pkg-podman:local"
    assert package_to_image_tag("virtual-desktop") == "pa-container-pkg-virtual-desktop:local"
    assert package_to_image_tag("sqlite_vec") == "pa-container-pkg-sqlite-vec:local"


def test_compute_package_hash(tmp_path: Path):
    pkg_dir = tmp_path / "pa_packages" / "sample"
    pkg_dir.mkdir(parents=True)
    manifest = pkg_dir / "package.yaml"
    manifest.write_text("name: sample\nversion: 1.0.0\n")

    h1 = compute_package_hash("sample", repo_root=tmp_path)
    assert len(h1) == 16

    # Modify file
    manifest.write_text("name: sample\nversion: 1.1.0\n")
    h2 = compute_package_hash("sample", repo_root=tmp_path)
    assert h1 != h2

    # Add extra file
    skill_dir = pkg_dir / "skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("# Skill\n")
    h3 = compute_package_hash("sample", repo_root=tmp_path)
    assert h2 != h3


def test_parse_package_manifest_full():
    data = {
        "schema_version": "2.0.0",
        "name": "full-tool",
        "version": "1.2.3",
        "description": "A comprehensive test tool",
        "payload": {
            "type": "binary_download",
            "platforms": {
                "x86_64": {
                    "url": "https://example.com/bin-x64.tar.gz",
                    "sha256": "abcdef123456",
                    "extract_map": {"bin/tool": "/usr/local/bin/tool"},
                }
            },
        },
        "skill": {
            "enabled": True,
            "source": "skill/SKILL.md",
        },
        "mcp": {
            "enabled": True,
            "server_id": "test-mcp",
            "command": "/usr/local/bin/tool",
            "args": ["mcp"],
            "env": {"FOO": "BAR"},
        },
        "runtime": {
            "devices": ["/dev/dri"],
            "cap_add": ["CAP_SYS_ADMIN"],
            "sysctl": {"net.ipv4.ip_forward": "1"},
            "env": {"DEBUG": "1"},
        },
        "egress": {
            "allow_hosts": ["example.com", "api.example.com"],
        },
        "token_replacer": [
            {
                "name": "test-token",
                "header": "Authorization",
                "pattern": "token ([A-Z]+)",
                "replacement": "token [REDACTED]",
            }
        ],
        "verification": {
            "command": "tool --version",
            "expected_output_contains": "1.2.3",
        },
    }
    manifest = parse_package_manifest(data)
    assert manifest.name == "full-tool"
    assert manifest.payload.type == "binary_download"
    assert manifest.skill.enabled is True
    assert manifest.mcp.server_id == "test-mcp"
    assert manifest.runtime.devices == ["/dev/dri"]
    assert manifest.egress.allow_hosts == ["example.com", "api.example.com"]
    assert len(manifest.token_replacer) == 1
    assert manifest.token_replacer[0].name == "test-token"


def test_projection_helpers():
    pkgs = discover_packages()
    active_manifests = [pkgs[k] for k in ("source-control/github", "podman") if k in pkgs]

    mcp_servers = get_mcp_servers_dict(active_manifests)
    assert "github" in mcp_servers
    assert mcp_servers["github"]["command"] == "/usr/local/bin/gh"

    egress = aggregate_egress_hosts(active_manifests)
    assert "api.github.com" in egress
    assert "docker.io" in egress

    tokens = aggregate_token_replacers(active_manifests)
    token_names = [t["name"] for t in tokens]
    assert "github-token-inject" in token_names
    gh_token = next(t for t in tokens if t["name"] == "github-token-inject")
    assert gh_token["replace_with"]["strategy"] == "static"
    assert gh_token["replace_with"]["value"] == "${ENV:GH_TOKEN}"
    assert gh_token["content_patterns"][0]["field"] == "headers"
    assert gh_token["content_patterns"][0]["header_name"] == "Authorization"
    assert gh_token["content_patterns"][0]["regex"] == "GH_TOKEN_PLACEHOLDER"
    # The base64 variant covers git's 'Authorization: Basic' credentials.
    assert any(cp.get("encoding") == "base64" for cp in gh_token["content_patterns"])
    assert "github.com" in gh_token["hostnames"]
    assert "raw.githubusercontent.com" in gh_token["hostnames"]

    privileges = aggregate_runtime_privileges(active_manifests)
    assert privileges["nested_containers"] is True
    assert "agent:1:999" in privileges["subuid_ranges"]


def test_generate_package_containerfile():
    pkgs = discover_packages()
    sc = pkgs["source-control/github"]
    cf_sc = generate_package_containerfile(sc, get_package_dir("source-control/github"))
    assert "FROM registry.fedoraproject.org/fedora-minimal:45 AS builder-base" in cf_sc
    assert "FROM builder-base AS artifact-source-control-github" in cf_sc
    assert "USER builder-source-control-github" in cf_sc
    assert "FROM scratch" in cf_sc
    assert "COPY --from=artifact-source-control-github /out/source-control-github/ /" in cf_sc

    podman = pkgs["podman"]
    cf_podman = generate_package_containerfile(podman, get_package_dir("podman"))
    assert "FROM registry.fedoraproject.org/fedora-minimal:45 AS builder-base" in cf_podman
    assert "FROM builder-base AS artifact-podman" in cf_podman
    assert "USER builder-podman" in cf_podman
    assert "bash /home/builder-podman/build/build.sh" in cf_podman
    assert "COPY --from=artifact-podman /out/podman/ /" in cf_podman


def test_package_image_tag_with_features():
    assert package_to_image_tag("document-tools") == "pa-container-pkg-document-tools:local"
    assert package_to_image_tag("document-tools/docling") == "pa-container-pkg-document-tools-docling:local"
    assert (
        package_to_image_tag("language-servers/rust-analyzer")
        == "pa-container-pkg-language-servers-rust-analyzer:local"
    )


def test_package_to_content_tag():
    from packages.discovery import package_to_content_tag

    assert package_to_content_tag("languages/rust", "abc12345") == "pa-container-pkg-languages-rust:abc12345"
    assert (
        package_to_content_tag("document-tools/docling", "def67890")
        == "pa-container-pkg-document-tools-docling:def67890"
    )


def test_assemble_package_skill(tmp_path: Path):
    pkg_dir = tmp_path / "pkg"
    skill_dir = pkg_dir / "skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# Core Capability\nBase instructions.")

    s0 = assemble_package_skill(pkg_dir)
    assert "# Core Capability" in s0
    assert "Base instructions." in s0

    pkg2_dir = tmp_path / "pkg2"
    (pkg2_dir / "skill").mkdir(parents=True)
    (pkg2_dir / "skill" / "base.md").write_text("# Base Markdown")
    s1 = assemble_package_skill(pkg2_dir)
    assert "# Base Markdown" in s1


def test_git_package_skill_assembly():
    """The git package carries no skill: git usage is common knowledge and the MCP tools self-register."""
    git_dir = get_package_dir("git")
    s_base = assemble_package_skill(git_dir)
    assert s_base == ""


def test_manifest_features_and_extensions():
    data = {
        "schema_version": "2.1.0",
        "name": "ext-tool",
        "version": "1.0.0",
        "features": {
            "subtool": {
                "description": "Subtool feature",
            }
        },
    }
    with pytest.raises(ValueError, match="defines 'features:'"):
        parse_package_manifest(data)

    data_no_feat = {
        "schema_version": "2.1.0",
        "name": "ext-tool",
        "version": "1.0.0",
        "extension": {
            "commands": [
                {
                    "name": "subcmd",
                    "help": "Run subcmd",
                    "handler": "ext.py:run_subcmd",
                }
            ],
            "flags": [
                {
                    "name": "--extra-flag",
                    "type": "str",
                    "default": "val",
                }
            ],
        },
        "hooks": {
            "container_args": "hooks.py:gen_args",
        },
        "integration": {
            "enabled": True,
            "command": "subtool run",
            "expected_output_contains": "success",
        },
    }
    m = parse_package_manifest(data_no_feat)
    assert len(m.extension.commands) == 1
    assert m.extension.commands[0].name == "subcmd"
    assert len(m.extension.flags) == 1
    assert m.hooks.container_args == "hooks.py:gen_args"
    assert m.integration.enabled is True
    assert m.integration.command == "subtool run"


def test_distro_package_manifest_parsing():
    import pytest

    data = {
        "name": "sys-tools",
        "version": "1.0.0",
        "payload": {
            "type": "distro_package",
            "packages": ["curl", "jq", "ripgrep"],
        },
    }
    manifest = parse_package_manifest(data)
    assert manifest.name == "sys-tools"
    assert manifest.payload.type == "distro_package"
    assert manifest.payload.packages == ["curl", "jq", "ripgrep"]

    empty_data = {
        "name": "invalid-pkg",
        "version": "1.0.0",
        "payload": {
            "type": "distro_package",
            "packages": [],
        },
    }
    with pytest.raises(ValueError, match="distro_package"):
        parse_package_manifest(empty_data)


def test_collect_distro_packages():
    manifests = {
        "pkg-a": parse_package_manifest(
            {
                "name": "pkg-a",
                "version": "1.0.0",
                "payload": {
                    "type": "distro_package",
                    "packages": ["python3", "uv"],
                },
            }
        ),
        "pkg-b": parse_package_manifest(
            {
                "name": "pkg-b",
                "version": "1.0.0",
                "payload": {
                    "type": "distro_package",
                    "packages": ["uv", "jq"],
                },
            }
        ),
        "pkg-c": parse_package_manifest(
            {
                "name": "pkg-c",
                "version": "1.0.0",
                "payload": {
                    "type": "build_script",
                    "script": "build.sh",
                },
            }
        ),
    }

    # pkg-a + pkg-b: should collect python3, uv, jq
    pkgs = collect_distro_packages({"pkg-a": [], "pkg-b": []}, manifests=manifests)
    assert pkgs == ["jq", "python3", "uv"]

    # pkg-c has build_script, no distro packages
    assert collect_distro_packages({"pkg-c": []}, manifests=manifests) == []


def test_generate_package_containerfile_distro_package(tmp_path: Path):
    manifest = parse_package_manifest(
        {
            "name": "distro-tool",
            "version": "1.0.0",
            "payload": {
                "type": "distro_package",
                "packages": ["curl"],
            },
        }
    )
    cf = generate_package_containerfile(manifest, tmp_path)
    assert "FROM builder-base AS artifact-distro-tool" in cf
    assert "USER builder-distro-tool" in cf
    assert "FROM scratch" in cf
    assert "COPY --from=artifact-distro-tool /out/distro-tool/ /" in cf


def test_resolve_package_dependencies_mocked():
    import pytest

    manifests = {
        "pkg-a": parse_package_manifest(
            {
                "name": "pkg-a",
                "version": "1.0.0",
                "runtime": {"dependencies": ["pkg-b"]},
            }
        ),
        "pkg-b": parse_package_manifest(
            {
                "name": "pkg-b",
                "version": "1.0.0",
                "runtime": {"dependencies": ["pkg-c"]},
            }
        ),
        "pkg-c": parse_package_manifest(
            {
                "name": "pkg-c",
                "version": "1.0.0",
            }
        ),
        "pkg-cycle-1": parse_package_manifest(
            {
                "name": "pkg-cycle-1",
                "version": "1.0.0",
                "runtime": {"dependencies": ["pkg-cycle-2"]},
            }
        ),
        "pkg-cycle-2": parse_package_manifest(
            {
                "name": "pkg-cycle-2",
                "version": "1.0.0",
                "runtime": {"dependencies": ["pkg-cycle-1"]},
            }
        ),
    }

    # Transitive dependency: pkg-a -> pkg-b -> pkg-c
    res = resolve_package_dependencies({"pkg-a": []}, manifests=manifests)
    keys = list(res.keys())
    assert keys == ["pkg-c", "pkg-b", "pkg-a"]
    assert res["pkg-c"] == []
    assert res["pkg-b"] == []
    assert res["pkg-a"] == []

    # Cycle detection
    with pytest.raises(ValueError, match="Circular package dependency detected"):
        resolve_package_dependencies({"pkg-cycle-1": []}, manifests=manifests)


def test_resolve_package_dependencies_real():
    # agents/pi depends on languages/node
    resolved = resolve_package_dependencies({"agents/pi": []})
    keys = list(resolved.keys())
    assert "languages/node" in keys
    assert "agents/pi" in keys
    assert keys.index("languages/node") < keys.index("agents/pi")

    # git/mcp depends on languages/python and git/base
    resolved_git_mcp = resolve_package_dependencies({"git/mcp": []})
    keys_git_mcp = list(resolved_git_mcp.keys())
    assert "languages/python" in keys_git_mcp
    assert "git/base" in keys_git_mcp
    assert "git/mcp" in keys_git_mcp
    assert keys_git_mcp.index("languages/python") < keys_git_mcp.index("git/mcp")

    # git/base does not depend on python
    resolved_git = resolve_package_dependencies({"git/base": []})
    assert "languages/python" not in resolved_git
    assert "git/base" in resolved_git

    # agent-orchestrators/t3 depends on languages/node and source-control
    resolved_t3 = resolve_package_dependencies({"agent-orchestrators/t3": []})
    keys_t3 = list(resolved_t3.keys())
    assert "languages/node" in keys_t3
    assert "source-control" in keys_t3
    assert "agent-orchestrators/t3" in keys_t3
    assert keys_t3.index("languages/node") < keys_t3.index("agent-orchestrators/t3")
    assert keys_t3.index("source-control") < keys_t3.index("agent-orchestrators/t3")

    # browser/chromium depends on languages/node and virtual-desktop
    resolved_browser_chromium = resolve_package_dependencies({"browser/chromium": []})
    keys_browser_chromium = list(resolved_browser_chromium.keys())
    assert "languages/node" in keys_browser_chromium
    assert "virtual-desktop" in keys_browser_chromium
    assert keys_browser_chromium.index("languages/node") < keys_browser_chromium.index("browser/chromium")

    # browser/chromium-headless pulls no virtual desktop
    resolved_browser_headless = resolve_package_dependencies({"browser/chromium-headless": []})
    assert "virtual-desktop" not in resolved_browser_headless
    assert "browser/chromium-headless" in resolved_browser_headless


def test_resolve_legacy_package_names_rejected():
    from packages.dependencies import REMOVED_LEGACY_PACKAGES

    for legacy, target in REMOVED_LEGACY_PACKAGES.items():
        with pytest.raises(ValueError, match=f"Package '{legacy}' has been consolidated into '{target}'"):
            resolve_package_dependencies({legacy: []})


def test_manifest_build_memory_mib():
    m1 = parse_package_manifest(
        {
            "name": "mem-tool",
            "version": "1.0.0",
            "build_memory_mib": 2048,
        }
    )
    assert m1.build_memory_mib == 2048

    m2 = parse_package_manifest(
        {
            "name": "default-tool",
            "version": "1.0.0",
        }
    )
    assert m2.build_memory_mib == 0


def test_generate_package_containerfile_rejects_features():
    with pytest.raises(ValueError, match="defines 'features:'"):
        parse_package_manifest(
            {
                "name": "mixed-pkg",
                "version": "1.0.0",
                "features": {
                    "mcp": {
                        "payload": {
                            "type": "build_script",
                            "script": "build.sh",
                        }
                    }
                },
            }
        )


def test_generate_package_containerfile_hybrid_payload(tmp_path: Path):
    manifest = parse_package_manifest(
        {
            "name": "hybrid-pkg",
            "version": "1.0.0",
            "payload": {
                "type": "build_script",
                "packages": ["ripgrep", "fd-find"],
                "script": "build.sh",
                "build_deps": ["cargo"],
            },
        }
    )
    cf = generate_package_containerfile(manifest, tmp_path)
    assert "FROM builder-base AS artifact-hybrid-pkg" in cf
    assert "USER builder-hybrid-pkg" in cf
    assert "cargo" in cf
    assert "ripgrep" in cf
    assert "fd-find" in cf
    assert "bash /home/builder-hybrid-pkg/build/build.sh" in cf


def test_collect_distro_packages_hybrid():
    manifests = {
        "pkg-hybrid": parse_package_manifest(
            {
                "name": "pkg-hybrid",
                "version": "1.0.0",
                "payload": {
                    "type": "build_script",
                    "packages": ["ripgrep", "fd-find"],
                    "script": "build.sh",
                },
            }
        ),
    }

    pkgs = collect_distro_packages({"pkg-hybrid": None}, manifests=manifests)
    assert pkgs == ["fd-find", "ripgrep"]


def test_generate_package_containerfile_entrypoint_staging(tmp_path: Path):
    manifest = parse_package_manifest(
        {
            "name": "hook-pkg",
            "version": "1.0.0",
            "payload": {
                "type": "distro_package",
                "packages": ["curl"],
            },
        }
    )
    cf = generate_package_containerfile(manifest, tmp_path)
    assert "entrypoint.d/root" in cf
    assert "entrypoint.d/agent" in cf


def test_manifest_features_required():
    with pytest.raises(ValueError, match="defines 'features:'"):
        parse_package_manifest(
            {
                "name": "required-feats",
                "version": "1.0.0",
                "features": {
                    "alpha": {"description": "Alpha feature"},
                },
            }
        )


def test_manifest_required_feature_per_feature_flag():
    with pytest.raises(ValueError, match="defines 'features:'"):
        parse_package_manifest(
            {
                "name": "per-required",
                "version": "1.0.0",
                "features": {
                    "core": {"description": "Core feature"},
                },
            }
        )


def test_media_packages_discovery_and_assembly():
    pkgs = discover_packages()

    media_pkgs = ["image-tools", "video-tools", "sound-tools", "3d-tools", "ocr-tools"]
    for pkg_name in media_pkgs:
        assert pkg_name in pkgs, f"Missing package: {pkg_name}"
        manifest = pkgs[pkg_name]
        assert manifest.category == "media"
        assert manifest.verification.command != ""

    # 1. image-tools & subpackages
    assert "image-tools/base" in pkgs
    assert "image-tools/vips" in pkgs
    assert "image-tools/jxl-heif" in pkgs
    assert "image-tools/gmic" in pkgs
    img_base = pkgs["image-tools/base"]
    assert "ImageMagick" in img_base.payload.packages
    assert "potrace" in img_base.payload.packages
    s_vips = assemble_package_skill(get_package_dir("image-tools/vips"))
    assert "vips" in s_vips

    # 2. video-tools
    vid_mf = pkgs["video-tools"]
    assert "ffmpeg-free" in vid_mf.payload.packages
    assert "mediainfo" in vid_mf.payload.packages
    assert "mkvtoolnix" in vid_mf.payload.packages
    s_vid = assemble_package_skill(get_package_dir("video-tools"))
    assert "ffmpeg-free" in s_vid

    # 3. sound-tools & subpackages
    assert "sound-tools/base" in pkgs
    assert "sound-tools/whisper" in pkgs
    snd_base = pkgs["sound-tools/base"]
    assert "sox" in snd_base.payload.packages
    assert "faad2" in snd_base.payload.packages
    s_whisper = assemble_package_skill(get_package_dir("sound-tools/whisper"))
    assert "whisper" in s_whisper

    # 4. 3d-tools & subpackages
    assert "3d-tools/base" in pkgs
    assert "3d-tools/trimesh" in pkgs
    assert "3d-tools/blender" in pkgs
    assert "3d-tools/meshlab" in pkgs
    assert "3d-tools/openscad" in pkgs
    td_base = pkgs["3d-tools/base"]
    assert "assimp" in td_base.payload.packages
    assert "admesh" in td_base.payload.packages
    s_blender = assemble_package_skill(get_package_dir("3d-tools/blender"))
    assert "blender" in s_blender

    # 5. ocr-tools & subpackages
    assert "ocr-tools/base" in pkgs
    assert "ocr-tools/ocrmypdf" in pkgs
    assert "ocr-tools/languages" in pkgs
    assert "ocr-tools/lang-fin" in pkgs
    ocr_base = pkgs["ocr-tools/base"]
    assert "tesseract" in ocr_base.payload.packages
    s_ocr = assemble_package_skill(get_package_dir("ocr-tools/ocrmypdf"))
    assert "ocrmypdf" in s_ocr
