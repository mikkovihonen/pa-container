from __future__ import annotations

import sys
from typing import TYPE_CHECKING

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
    assert "python" in pkgs
    assert "node" in pkgs
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
    active_manifests = [pkgs[k] for k in ("source-control", "podman") if k in pkgs]
    active_features = {"source-control": ["github"]}

    mcp_servers = get_mcp_servers_dict(active_manifests, active_features=active_features)
    assert "github" in mcp_servers
    assert mcp_servers["github"]["command"] == "/usr/local/bin/gh"

    egress = aggregate_egress_hosts(active_manifests, active_features=active_features)
    assert "api.github.com" in egress
    assert "docker.io" in egress

    tokens = aggregate_token_replacers(active_manifests, active_features=active_features)
    token_names = [t["name"] for t in tokens]
    assert "github-token" in token_names
    gh_token = next(t for t in tokens if t["name"] == "github-token")
    assert gh_token["replace_with"]["strategy"] == "static"
    assert gh_token["content_patterns"][0]["field"] == "headers"
    assert gh_token["content_patterns"][0]["header_name"] == "Authorization"

    privileges = aggregate_runtime_privileges(active_manifests)
    assert privileges["nested_containers"] is True
    assert "agent:1:999" in privileges["subuid_ranges"]


def test_generate_package_containerfile():
    pkgs = discover_packages()
    sc = pkgs["source-control"]
    cf_sc = generate_package_containerfile(sc, get_package_dir("source-control"), active_features=["github"])
    assert "FROM registry.fedoraproject.org/fedora-minimal:45 AS builder-base" in cf_sc
    assert "FROM builder-base AS artifact-source-control" in cf_sc
    assert "USER builder-source-control" in cf_sc
    assert "bash /home/builder-source-control/build/features/github/build.sh" in cf_sc
    assert "FROM scratch" in cf_sc
    assert "COPY --from=artifact-source-control /out/source-control/ /" in cf_sc

    podman = pkgs["podman"]
    cf_podman = generate_package_containerfile(podman, get_package_dir("podman"))
    assert "FROM registry.fedoraproject.org/fedora-minimal:45 AS builder-base" in cf_podman
    assert "FROM builder-base AS artifact-podman" in cf_podman
    assert "USER builder-podman" in cf_podman
    assert "bash /home/builder-podman/build/build.sh" in cf_podman
    assert "COPY --from=artifact-podman /out/podman/ /" in cf_podman


def test_package_image_tag_with_features():
    assert package_to_image_tag("document-tools") == "pa-container-pkg-document-tools:local"
    assert (
        package_to_image_tag("document-tools", features=["docling"]) == "pa-container-pkg-document-tools--docling:local"
    )
    assert (
        package_to_image_tag("language-servers", features=["rust-analyzer", "pyright"])
        == "pa-container-pkg-language-servers--pyright--rust-analyzer:local"
    )


def test_assemble_package_skill(tmp_path: Path):
    pkg_dir = tmp_path / "pkg"
    skill_dir = pkg_dir / "skill"
    features_dir = skill_dir / "features"
    features_dir.mkdir(parents=True)

    (skill_dir / "base.md").write_text("# Core Capability\nBase instructions.")
    (features_dir / "featA.md").write_text("## Feature A\nFeature A instructions.")
    (features_dir / "featB.md").write_text("## Feature B\nFeature B instructions.")

    # Without features: only base
    s0 = assemble_package_skill(pkg_dir)
    assert "# Core Capability" in s0
    assert "Feature A" not in s0
    assert "Feature B" not in s0

    # With featA: base + featA
    s1 = assemble_package_skill(pkg_dir, active_features=["featA"])
    assert "# Core Capability" in s1
    assert "Feature A" in s1
    assert "Feature B" not in s1

    # With both
    s2 = assemble_package_skill(pkg_dir, active_features=["featA", "featB"])
    assert "# Core Capability" in s2
    assert "Feature A" in s2
    assert "Feature B" in s2


def test_git_package_skill_assembly():
    git_dir = get_package_dir("git")
    s_base = assemble_package_skill(git_dir, active_features=[])
    assert "Git Version Control" in s_base
    assert "Git MCP Server" not in s_base

    s_mcp = assemble_package_skill(git_dir, active_features=["mcp"])
    assert "Git Version Control" in s_mcp
    assert "Git MCP Server" in s_mcp


def test_manifest_features_and_extensions():
    data = {
        "schema_version": "2.1.0",
        "name": "ext-tool",
        "version": "1.0.0",
        "features": {
            "subtool": {
                "description": "Subtool feature",
                "default": False,
                "payload": {
                    "type": "build_script",
                    "script": "subtool/build.sh",
                },
                "skill_fragment": "skill/features/subtool.md",
                "verification": {
                    "command": "subtool --version",
                    "expected_output_contains": "1.0",
                },
            }
        },
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
    m = parse_package_manifest(data)
    assert "subtool" in m.features
    assert m.features["subtool"].description == "Subtool feature"
    assert m.features["subtool"].skill_fragment == "skill/features/subtool.md"
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
                "features": {
                    "extra": {
                        "payload": {
                            "type": "distro_package",
                            "packages": ["python3-pip", "git"],
                        }
                    }
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

    # pkg-a without features + pkg-b: should collect python3, uv, jq
    pkgs = collect_distro_packages({"pkg-a": [], "pkg-b": []}, manifests=manifests)
    assert pkgs == ["jq", "python3", "uv"]

    # pkg-a with extra feature + pkg-b: should collect git, jq, python3, python3-pip, uv
    pkgs_extra = collect_distro_packages({"pkg-a": ["extra"], "pkg-b": []}, manifests=manifests)
    assert pkgs_extra == ["git", "jq", "python3", "python3-pip", "uv"]

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
                "features": {
                    "feat-default": {
                        "default": True,
                    },
                    "feat-optional": {
                        "default": False,
                    },
                },
            }
        ),
        "pkg-c": parse_package_manifest(
            {
                "name": "pkg-c",
                "version": "1.0.0",
            }
        ),
        "pkg-feature-dep": parse_package_manifest(
            {
                "name": "pkg-feature-dep",
                "version": "1.0.0",
                "features": {
                    "extra": {
                        "runtime": {"dependencies": ["pkg-c"]},
                    }
                },
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
    # pkg-b should also inherit its default feature "feat-default"
    res = resolve_package_dependencies({"pkg-a": []}, manifests=manifests)
    keys = list(res.keys())
    assert keys == ["pkg-c", "pkg-b", "pkg-a"]
    assert res["pkg-c"] == []
    assert res["pkg-b"] == ["feat-default"]
    assert res["pkg-a"] == []

    # Feature-conditional dependency: inactive vs active
    res_no_feat = resolve_package_dependencies({"pkg-feature-dep": []}, manifests=manifests)
    assert res_no_feat == {"pkg-feature-dep": []}

    res_with_feat = resolve_package_dependencies({"pkg-feature-dep": ["extra"]}, manifests=manifests)
    assert list(res_with_feat.keys()) == ["pkg-c", "pkg-feature-dep"]
    assert res_with_feat["pkg-feature-dep"] == ["extra"]

    # Cycle detection
    with pytest.raises(ValueError, match="Circular package dependency detected"):
        resolve_package_dependencies({"pkg-cycle-1": []}, manifests=manifests)


def test_resolve_package_dependencies_real():
    # agents with pi depends on node
    resolved = resolve_package_dependencies({"agents": ["pi"]})
    keys = list(resolved.keys())
    assert "node" in keys
    assert "agents" in keys
    assert keys.index("node") < keys.index("agents")
    assert resolved["agents"] == ["pi"]
    assert resolved["node"] == []

    # git with mcp feature depends on python
    resolved_git_mcp = resolve_package_dependencies({"git": ["mcp"]})
    keys_git_mcp = list(resolved_git_mcp.keys())
    assert "python" in keys_git_mcp
    assert "git" in keys_git_mcp
    assert keys_git_mcp.index("python") < keys_git_mcp.index("git")
    assert resolved_git_mcp["git"] == ["mcp"]

    # git without mcp feature does not depend on python
    resolved_git = resolve_package_dependencies({"git": []})
    assert "python" not in resolved_git
    assert "git" in resolved_git

    # t3 depends on node and source-control
    resolved_t3 = resolve_package_dependencies({"t3": []})
    keys_t3 = list(resolved_t3.keys())
    assert "node" in keys_t3
    assert "source-control" in keys_t3
    assert "t3" in keys_t3
    assert keys_t3.index("node") < keys_t3.index("t3")
    assert keys_t3.index("source-control") < keys_t3.index("t3")


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


def test_generate_package_containerfile_mixed_payload(tmp_path: Path):
    manifest = parse_package_manifest(
        {
            "name": "mixed-pkg",
            "version": "1.0.0",
            "payload": {
                "type": "distro_package",
                "packages": ["git"],
            },
            "features": {
                "mcp": {
                    "payload": {
                        "type": "build_script",
                        "script": "features/mcp/build.sh",
                        "build_deps": ["python3-pip"],
                    }
                }
            },
        }
    )

    # Without features: pure distro package creates artifact stage without build script
    cf_no_feat = generate_package_containerfile(manifest, tmp_path, active_features=[])
    assert "FROM builder-base AS artifact-mixed-pkg" in cf_no_feat
    assert "USER builder-mixed-pkg" in cf_no_feat
    assert "RUN bash /home" not in cf_no_feat

    # With mcp feature: mixed payload compiles mcp feature script under builder-mixed-pkg
    cf_with_feat = generate_package_containerfile(manifest, tmp_path, active_features=["mcp"])
    assert "FROM builder-base AS artifact-mixed-pkg" in cf_with_feat
    assert "USER builder-mixed-pkg" in cf_with_feat
    assert "python3-pip" in cf_with_feat
    assert "git" in cf_with_feat
    assert "bash /home/builder-mixed-pkg/build/features/mcp/build.sh" in cf_with_feat


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


def test_collect_distro_packages_hybrid_and_feature_handling():
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
                "features": {
                    "extra": {
                        "default": True,
                        "payload": {
                            "type": "distro_package",
                            "packages": ["tree-sitter-cli"],
                        },
                    }
                },
            }
        ),
    }

    # active_feats=None -> uses default feature: ripgrep, fd-find, tree-sitter-cli
    pkgs_default = collect_distro_packages({"pkg-hybrid": None}, manifests=manifests)
    assert pkgs_default == ["fd-find", "ripgrep", "tree-sitter-cli"]

    # active_feats=[] -> explicit empty list disables default features
    pkgs_explicit_empty = collect_distro_packages({"pkg-hybrid": []}, manifests=manifests)
    assert pkgs_explicit_empty == ["fd-find", "ripgrep"]


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
