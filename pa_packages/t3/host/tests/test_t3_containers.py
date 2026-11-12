from __future__ import annotations

import json
import sys
from unittest.mock import MagicMock, patch

from pa_packages.t3.host.containers import find_running_t3_container


class TestFindRunningT3Container:
    def test_find_by_mode_label(self, tmp_path):
        ps_data = [
            {
                "Names": ["pa-container-agent-12345"],
                "Id": "abc123456789",
                "Labels": {
                    "pa-container.project.hash": "test-hash",
                    "pa-container.type": "agent",
                    "pa-container.mode": "t3",
                    "pa-container.launcher_pid": str(sys.maxsize),
                },
                "State": "running",
                "Status": "Up 5 minutes",
            }
        ]

        with (
            patch("pa_packages.t3.host.containers.project_key", return_value="test-hash"),
            patch("subprocess.run") as mock_run,
            patch("pa_packages.t3.host.containers.is_pid_alive", return_value=True),
        ):
            mock_run.return_value = MagicMock(returncode=0, stdout=json.dumps(ps_data))
            info = find_running_t3_container(tmp_path)

        assert info is not None
        assert info.container_name == "pa-container-agent-12345"
        assert info.container_id == "abc123456789"
        assert info.project_hash == "test-hash"
        assert info.launcher_pid == sys.maxsize

    def test_find_by_mount(self, tmp_path):
        ps_data = [
            {
                "Names": ["pa-container-agent-legacy"],
                "Id": "def987654321",
                "Labels": {
                    "pa-container.project.hash": "test-hash",
                    "pa-container.type": "agent",
                },
                "Mounts": ["/home/agent/.t3"],
                "State": "running",
            }
        ]

        with (
            patch("pa_packages.t3.host.containers.project_key", return_value="test-hash"),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0, stdout=json.dumps(ps_data))
            info = find_running_t3_container(tmp_path)

        assert info is not None
        assert info.container_name == "pa-container-agent-legacy"

    def test_find_by_inspect_env(self, tmp_path):
        ps_data = [
            {
                "Names": ["pa-container-agent-env"],
                "Id": "ghi123456789",
                "Labels": {
                    "pa-container.project.hash": "test-hash",
                    "pa-container.type": "agent",
                },
                "Mounts": [],
                "State": "running",
            }
        ]

        def fake_run(cmd, *args, **kwargs):
            if "ps" in cmd:
                return MagicMock(returncode=0, stdout=json.dumps(ps_data))
            elif "inspect" in cmd:
                return MagicMock(returncode=0, stdout='["PA_CONTAINER_MODE=t3", "VAR=val"]')
            return MagicMock(returncode=1, stdout="")

        with (
            patch("pa_packages.t3.host.containers.project_key", return_value="test-hash"),
            patch("subprocess.run", side_effect=fake_run),
        ):
            info = find_running_t3_container(tmp_path)

        assert info is not None
        assert info.container_name == "pa-container-agent-env"

    def test_ignores_non_t3_container(self, tmp_path):
        ps_data = [
            {
                "Names": ["pa-container-agent-cli"],
                "Id": "jkl123456789",
                "Labels": {
                    "pa-container.project.hash": "test-hash",
                    "pa-container.type": "agent",
                    "pa-container.mode": "cli",
                },
                "Mounts": ["/workspace"],
                "State": "running",
            }
        ]

        def fake_run(cmd, *args, **kwargs):
            if "ps" in cmd:
                return MagicMock(returncode=0, stdout=json.dumps(ps_data))
            elif "inspect" in cmd:
                return MagicMock(returncode=0, stdout='["PA_CONTAINER_MODE=cli"]')
            return MagicMock(returncode=1, stdout="")

        with (
            patch("pa_packages.t3.host.containers.project_key", return_value="test-hash"),
            patch("subprocess.run", side_effect=fake_run),
        ):
            info = find_running_t3_container(tmp_path)

        assert info is None

    def test_ignores_dead_launcher_pid(self, tmp_path):
        ps_data = [
            {
                "Names": ["pa-container-agent-dead"],
                "Id": "mno123456789",
                "Labels": {
                    "pa-container.project.hash": "test-hash",
                    "pa-container.type": "agent",
                    "pa-container.mode": "t3",
                    "pa-container.launcher_pid": "99999999",
                },
                "State": "running",
            }
        ]

        with (
            patch("pa_packages.t3.host.containers.project_key", return_value="test-hash"),
            patch("subprocess.run") as mock_run,
            patch("pa_packages.t3.host.containers.is_pid_alive", return_value=False),
        ):
            mock_run.return_value = MagicMock(returncode=0, stdout=json.dumps(ps_data))
            info = find_running_t3_container(tmp_path)

        assert info is None

    def test_no_containers(self, tmp_path):
        with (
            patch("pa_packages.t3.host.containers.project_key", return_value="test-hash"),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0, stdout="[]")
            info = find_running_t3_container(tmp_path)

        assert info is None

    def test_command_failure_handled(self, tmp_path):
        with (
            patch("pa_packages.t3.host.containers.project_key", return_value="test-hash"),
            patch("subprocess.run", side_effect=RuntimeError("podman error")),
        ):
            info = find_running_t3_container(tmp_path)

        assert info is None
