from __future__ import annotations

from pa_packages.ios_simulator.host.plugin import IOSSimulatorPlugin

from guest_daemon.ios_runner import IOSRunnerDaemon


class TestIOSRunnerDaemon:
    def test_create_and_boot_simulator_mock(self):
        daemon = IOSRunnerDaemon()
        udid = daemon.create_and_boot_simulator("agent1", mock=True)
        assert udid == "MOCK-UDID-AGENT1"
        assert daemon.simulators["agent1"] == "MOCK-UDID-AGENT1"

    def test_install_and_launch_app_mock(self, tmp_path):
        daemon = IOSRunnerDaemon()
        daemon.simulators["agent1"] = "MOCK-UDID-AGENT1"
        res = daemon.install_and_launch_app("agent1", tmp_path / "App.app", "com.example.app", mock=True)
        assert res is True

    def test_capture_screenshot_mock(self, tmp_path):
        daemon = IOSRunnerDaemon()
        daemon.simulators["agent1"] = "MOCK-UDID-AGENT1"
        out_png = tmp_path / "screen.png"
        res = daemon.capture_screenshot("agent1", out_png, mock=True)
        assert res == out_png
        assert out_png.is_file()

    def test_delete_simulator_mock(self):
        daemon = IOSRunnerDaemon()
        daemon.simulators["agent1"] = "MOCK-UDID-AGENT1"
        daemon.delete_simulator("agent1", mock=True)
        assert "agent1" not in daemon.simulators


class TestIOSSimulatorPlugin:
    def test_contribute_tools(self):
        plugin = IOSSimulatorPlugin()
        tools = plugin.contribute_tools()
        assert len(tools) >= 5
        names = [t["name"] for t in tools]
        assert "ios_build_and_install" in names
        assert "ios_screenshot" in names
        assert "ios_tap" in names
        assert "ios_type" in names
        assert "ios_xctest" in names
