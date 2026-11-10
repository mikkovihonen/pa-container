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
    compute_package_hash,
    discover_packages,
    get_mcp_servers_dict,
    get_package_dir,
    package_to_image_tag,
    parse_package_manifest,
)
from packages.builder import generate_package_containerfile


def test_discover_packages():
    pkgs = discover_packages()
    assert len(pkgs) >= 20
    assert "podman" in pkgs
    assert "python" in pkgs
    assert "node" in pkgs
    assert "gh" in pkgs
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
    pkg_dir = tmp_path / "packages" / "sample"
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
    active_manifests = [pkgs[k] for k in ("gh", "podman") if k in pkgs]

    mcp_servers = get_mcp_servers_dict(active_manifests)
    assert "github" in mcp_servers
    assert mcp_servers["github"]["command"] == "/usr/local/bin/gh"

    egress = aggregate_egress_hosts(active_manifests)
    assert "api.github.com" in egress
    assert "docker.io" in egress

    tokens = aggregate_token_replacers(active_manifests)
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
    gh = pkgs["gh"]
    cf_gh = generate_package_containerfile(gh, get_package_dir("gh"))
    assert "FROM registry.fedoraproject.org/fedora-minimal:45 AS extractor" in cf_gh
    assert "FROM scratch" in cf_gh
    assert "COPY --from=extractor /out/ /" in cf_gh

    podman = pkgs["podman"]
    cf_podman = generate_package_containerfile(podman, get_package_dir("podman"))
    assert "FROM registry.fedoraproject.org/fedora-minimal:45 AS builder" in cf_podman
    assert "bash /build/build.sh" in cf_podman
