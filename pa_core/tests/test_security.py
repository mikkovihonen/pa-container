from pathlib import Path

import pytest
import yaml

from security import (
    is_ip_in_blocked_ranges,
    read_security_config,
    validate_mount_paths,
)

SAMPLE_BLOCKED_MOUNTS = [
    "~/.ssh",
    "~/.gnupg",
    "~/.aws",
    "~/.azure",
    "~/.config/gcloud",
    "~/.kube",
    "~/.docker",
    "/var/run/docker.sock",
    "/var/run/podman/podman.sock",
    "/etc/shadow",
    "/etc/passwd",
    "/etc/sudoers",
    "/root",
]

SAMPLE_BLOCKED_IPS = [
    "127.0.0.0/8",
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "169.254.0.0/16",
    "::1/128",
    "fc00::/7",
    "fe80::/10",
]


class TestReadSecurityConfig:
    def _write_config(self, tmp_path: Path, data: dict):
        (tmp_path / "config.yaml").write_text(yaml.dump(data))

    def test_missing_config_raises_file_not_found(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            read_security_config(tmp_path)

    def test_missing_security_section_raises_value_error(self, tmp_path: Path):
        self._write_config(tmp_path, {})
        with pytest.raises(ValueError, match="Missing required 'security' configuration section"):
            read_security_config(tmp_path)

    def test_valid_security_config(self, tmp_path: Path):
        self._write_config(
            tmp_path,
            {
                "security": {
                    "read_only_git_hooks": False,
                    "blocked_mount_paths": ["~/.custom_secret"],
                    "blocked_ip_ranges": ["10.0.0.0/8"],
                    "git_config_allowlist": ["user.name"],
                }
            },
        )
        cfg = read_security_config(tmp_path)
        assert cfg["read_only_git_hooks"] is False
        assert cfg["blocked_mount_paths"] == ["~/.custom_secret"]
        assert cfg["blocked_ip_ranges"] == ["10.0.0.0/8"]
        assert cfg["git_config_allowlist"] == ["user.name"]


class TestValidateMountPaths:
    def test_safe_mounts_pass(self, tmp_path: Path):
        safe_dir = tmp_path / "safe_dir"
        safe_dir.mkdir()
        mounts = [
            f"{safe_dir}:/home/agent/safe:ro",
            f"{tmp_path}/cache:/home/agent/cache",
        ]
        errors = validate_mount_paths(mounts, SAMPLE_BLOCKED_MOUNTS)
        assert errors == []

    def test_blocked_mount_paths_detected(self):
        ssh_dir = str(Path("~/.ssh").expanduser())
        mounts = [
            f"{ssh_dir}:/home/agent/.ssh",
            f"{ssh_dir}/id_rsa:/home/agent/.ssh/id_rsa:ro",
            "/var/run/docker.sock:/var/run/docker.sock",
            "/etc/shadow:/home/agent/shadow:ro",
        ]
        errors = validate_mount_paths(mounts, SAMPLE_BLOCKED_MOUNTS)
        assert len(errors) == 4
        assert any("~/.ssh" in e for e in errors)
        assert any("/var/run/docker.sock" in e for e in errors)
        assert any("/etc/shadow" in e for e in errors)

    def test_forbidden_container_destinations_detected(self, tmp_path: Path):
        safe_file = tmp_path / "custom.yaml"
        safe_file.write_text("safe: true")
        mounts = [
            f"{safe_file}:/workspace/.pa-container/allowlist.yaml:rw",
            f"{safe_file}:/workspace/.git/hooks/pre-commit:rw",
            f"{safe_file}:/etc/hosts:rw",
            f"{safe_file}:/usr/bin/bash:rw",
            f"{safe_file}:relative/path:ro",
        ]
        errors = validate_mount_paths(mounts, SAMPLE_BLOCKED_MOUNTS)
        assert len(errors) == 5
        assert any("/workspace/.pa-container" in e for e in errors)
        assert any("/workspace/.git/hooks" in e for e in errors)
        assert any("/etc" in e for e in errors)
        assert any("/usr" in e for e in errors)
        assert any("absolute path starting with '/'" in e for e in errors)


class TestIsIpInBlockedRanges:
    def test_private_and_metadata_ips_are_blocked(self):
        ranges = SAMPLE_BLOCKED_IPS
        assert is_ip_in_blocked_ranges("127.0.0.1", ranges)
        assert is_ip_in_blocked_ranges("10.1.2.3", ranges)
        assert is_ip_in_blocked_ranges("172.16.5.5", ranges)
        assert is_ip_in_blocked_ranges("192.168.1.1", ranges)
        assert is_ip_in_blocked_ranges("169.254.169.254", ranges)
        assert is_ip_in_blocked_ranges("::1", ranges)
        assert is_ip_in_blocked_ranges("fe80::1", ranges)

    def test_public_ips_are_not_blocked(self):
        ranges = SAMPLE_BLOCKED_IPS
        assert not is_ip_in_blocked_ranges("8.8.8.8", ranges)
        assert not is_ip_in_blocked_ranges("1.1.1.1", ranges)
        assert not is_ip_in_blocked_ranges("93.184.216.34", ranges)
        assert not is_ip_in_blocked_ranges("invalid_ip", ranges)


class TestProxyIsolation:
    def test_proxy_entrypoint_protects_mitmweb_from_agent_interface(self):
        root_dir = Path(__file__).resolve().parent.parent.parent
        entrypoint = root_dir / "coding-agent-proxy" / "entrypoint.sh"
        assert entrypoint.exists()
        content = entrypoint.read_text()
        assert "ipt -A INPUT -i eth1 -p tcp --dport 8081 -j REJECT --reject-with tcp-reset" in content
        assert "ipt -A INPUT -i eth1 -p udp --dport 8081 -j DROP" in content
        assert "--web-host 0.0.0.0" in content
