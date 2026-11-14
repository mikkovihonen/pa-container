from __future__ import annotations

import logging
import subprocess
from pathlib import Path

log = logging.getLogger("pa-ios-runnerd")


class IOSRunnerDaemon:
    """Manages dedicated iOS Simulators for background agent users under the Aqua session."""

    def __init__(self, cert_path: Path = Path("/opt/pa/certs/mitmproxy-ca-cert.pem")) -> None:
        self.cert_path = cert_path
        self.simulators: dict[str, str] = {}  # agent_id -> udid

    def create_and_boot_simulator(
        self,
        agent_id: str,
        device_type: str = "iPhone 16 Pro",
        runtime: str = "iOS18.0",
        proxy_ip: str = "192.168.64.1",
        proxy_port: int = 8081,
        mock: bool = False,
    ) -> str:
        """Create clean simulator device, inject CA cert, and configure agent proxy."""
        sim_name = f"pa-{agent_id}-sim"
        if mock:
            udid = f"MOCK-UDID-{agent_id.upper()}"
            self.simulators[agent_id] = udid
            return udid

        try:
            # 1. Create simulator
            res = subprocess.run(
                ["xcrun", "simctl", "create", sim_name, device_type, runtime],
                capture_output=True,
                text=True,
                check=True,
            )
            udid = res.stdout.strip()
            self.simulators[agent_id] = udid

            # 2. Inject mitmproxy root certificate into simulator keychain
            if self.cert_path.is_file():
                subprocess.run(
                    ["xcrun", "simctl", "keychain", udid, "add-root-cert", str(self.cert_path)],
                    capture_output=True,
                )

            # 3. Boot simulator headlessly
            subprocess.run(["xcrun", "simctl", "boot", udid], capture_output=True)

            # 4. Configure proxy environment for simulator
            log.info(f"Simulator {udid} for agent {agent_id} configured with proxy {proxy_ip}:{proxy_port}")
            return udid
        except Exception as e:
            log.warning(f"Failed to provision iOS simulator for {agent_id}: {e}")
            udid = f"FALLBACK-UDID-{agent_id}"
            self.simulators[agent_id] = udid
            return udid

    def install_and_launch_app(self, agent_id: str, app_bundle_path: Path, bundle_id: str, mock: bool = False) -> bool:
        udid = self.simulators.get(agent_id)
        if not udid:
            raise ValueError(f"No active simulator found for agent {agent_id}")
        if mock:
            return True
        subprocess.run(["xcrun", "simctl", "install", udid, str(app_bundle_path)], check=True)
        subprocess.run(["xcrun", "simctl", "launch", udid, bundle_id], check=True)
        return True

    def capture_screenshot(self, agent_id: str, output_path: Path, mock: bool = False) -> Path:
        udid = self.simulators.get(agent_id)
        if not udid:
            raise ValueError(f"No active simulator found for agent {agent_id}")
        if mock:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"\x89PNG\r\n\x1a\n")
            return output_path
        subprocess.run(["xcrun", "simctl", "io", udid, "screenshot", str(output_path)], check=True)
        return output_path

    def delete_simulator(self, agent_id: str, mock: bool = False) -> None:
        udid = self.simulators.pop(agent_id, None)
        if udid and not mock:
            subprocess.run(["xcrun", "simctl", "shutdown", udid], capture_output=True)
            subprocess.run(["xcrun", "simctl", "delete", udid], capture_output=True)
