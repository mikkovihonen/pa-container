from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def generate_pf_conf(
    proxy_ip: str,
    dns_port: int,
    agents: list[dict[str, Any]],
    control_port: int = 2222,
) -> str:
    """Generate macOS /etc/pf.conf UID-to-port lockdown rules."""
    user_list = ["_pa_daemon"] + [a.get("user") or a.get("id") or f"agent{i + 1}" for i, a in enumerate(agents)]
    users_clause = "user { " + ", ".join(user_list) + " }"

    lines = [
        f'proxy_ip = "{proxy_ip}"',
        f'dns_port = "{dns_port}"',
        "",
        "set block-policy return",
        "set skip on lo0",
        "",
        "# Default deny all outbound and inbound traffic",
        "block in all",
        "block out all",
        "",
        "# Inbound control from host gateway",
        f"pass in quick proto tcp from $proxy_ip to any port {control_port} keep state",
        "",
        "# Allow DNS queries ONLY to external proxy DNS listener",
        f"pass out quick proto {{ tcp, udp }} from any to $proxy_ip port $dns_port {users_clause} keep state",
        "",
        "# Strict UID-to-Proxy-Port lockdown per agent user",
        "pass out quick proto tcp from any to $proxy_ip port 8080 user _pa_daemon keep state",
    ]

    for a in agents:
        user = a.get("user") or a.get("id") or "agent1"
        proxy_port = a.get("proxy_port", 8081)
        transparent_port = a.get("transparent_port")
        if transparent_port and transparent_port != proxy_port:
            lines.append(
                f"pass out quick proto tcp from any to $proxy_ip port {{ {proxy_port}, {transparent_port} }} user {user} keep state"
            )
        else:
            lines.append(f"pass out quick proto tcp from any to $proxy_ip port {proxy_port} user {user} keep state")

    lines.append("")
    return "\n".join(lines)


def generate_nftables_conf(
    proxy_ip: str,
    dns_port: int,
    agents: list[dict[str, Any]],
    control_port: int = 2222,
) -> str:
    """Generate Linux /etc/nftables.conf UID-to-port rules with transparent DNAT."""
    agent_users = [f'"{a.get("user") or a.get("id")}"' for a in agents]
    all_users = ['"_pa_daemon"'] + agent_users
    users_set = "{ " + ", ".join(all_users) + " }"

    lines = [
        "flush ruleset",
        "",
        f"define PROXY_IP = {proxy_ip}",
        f"define DNS_PORT = {dns_port}",
        "",
        "table ip pa_factory {",
        "    chain nat_output {",
        "        type nat hook output priority -100; policy accept;",
        "",
        "        # Exclude loopback and direct proxy target",
        "        ip daddr 127.0.0.0/8 return",
        "        ip daddr $PROXY_IP return",
        "",
        "        # Redirect all direct DNS traffic from agents to coding-agent-proxy DNS",
        "        meta skuid >= 2001 udp dport 53 dnat to $PROXY_IP:$DNS_PORT",
        "        meta skuid >= 2001 tcp dport 53 dnat to $PROXY_IP:$DNS_PORT",
        "",
        "        # Redirect direct HTTP/HTTPS calls to transparent proxy ports",
    ]

    for a in agents:
        user = a.get("user") or a.get("id") or "agent1"
        t_port = a.get("transparent_port") or (a.get("proxy_port", 8081) + 10)
        lines.append(f'        meta skuid "{user}" tcp dport {{ 80, 443 }} dnat to $PROXY_IP:{t_port}')

    lines.extend(
        [
            "    }",
            "",
            "    chain filter_output {",
            "        type filter hook output priority 0; policy drop;",
            "",
            '        oifname "lo" accept',
            "        ct state established,related accept",
            "",
            "        # Allow DNS to proxy for all registered agent users",
            f"        meta skuid {users_set} ip daddr $PROXY_IP udp dport $DNS_PORT accept",
            f"        meta skuid {users_set} ip daddr $PROXY_IP tcp dport $DNS_PORT accept",
            "",
            '        meta skuid "_pa_daemon" ip daddr $PROXY_IP tcp dport 8080 accept',
        ]
    )

    for a in agents:
        user = a.get("user") or a.get("id") or "agent1"
        p_port = a.get("proxy_port", 8081)
        t_port = a.get("transparent_port") or (p_port + 10)
        if t_port != p_port:
            lines.append(f'        meta skuid "{user}" ip daddr $PROXY_IP tcp dport {{ {p_port}, {t_port} }} accept')
        else:
            lines.append(f'        meta skuid "{user}" ip daddr $PROXY_IP tcp dport {p_port} accept')

    lines.extend(
        [
            "    }",
            "}",
            "",
        ]
    )
    return "\n".join(lines)


def apply_firewall(
    rules_content: str,
    config_path: Path | None = None,
    mock: bool = False,
) -> Path:
    """Write rules and reload guest firewall (pf on macOS, nftables on Linux)."""
    if mock and config_path is None:
        target = Path("/tmp/pa_mock_firewall.conf")
        target.write_text(rules_content)
        return target

    if config_path is None:
        target = Path("/etc/pf.conf") if sys.platform == "darwin" else Path("/etc/nftables.conf")
    else:
        target = config_path

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(rules_content)

    if not mock:
        if sys.platform == "darwin":
            try:
                subprocess.run(["pfctl", "-e"], capture_output=True)
                subprocess.run(["pfctl", "-f", str(target)], check=True, capture_output=True)
            except Exception as e:
                log.warning(f"Failed to reload pfctl: {e}")
        else:
            try:
                subprocess.run(["nft", "-f", str(target)], check=True, capture_output=True)
            except Exception as e:
                log.warning(f"Failed to reload nftables: {e}")

    return target
