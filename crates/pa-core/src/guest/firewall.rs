use anyhow::Result;
use serde::{Deserialize, Serialize};
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentFirewallRule {
    pub user: String,
    pub proxy_port: u16,
    pub transparent_port: Option<u16>,
}

pub fn generate_pf_conf(
    proxy_ip: &str,
    dns_port: u16,
    agents: &[AgentFirewallRule],
    control_port: u16,
) -> String {
    let mut users = vec!["_pa_daemon".to_string()];
    for a in agents {
        users.push(a.user.clone());
    }
    let users_clause = users.join(", ");

    let mut out = format!(
        r#"proxy_ip = "{proxy_ip}"
dns_port = "{dns_port}"

set block-policy return
set skip on lo0

# Default deny all outbound and inbound traffic
block in all
block out all

# Inbound control from host gateway
pass in quick proto tcp from $proxy_ip to any port {control_port} keep state

# Allow DNS queries ONLY to external proxy DNS listener
pass out quick proto {{ tcp, udp }} from any to $proxy_ip port $dns_port user {{ {users_clause} }} keep state

# Strict UID-to-Proxy-Port lockdown per agent user
pass out quick proto tcp from any to $proxy_ip port 8080 user _pa_daemon keep state
"#
    );

    for a in agents {
        if a.proxy_port == 0 {
            out.push_str(&format!(
                "pass out quick proto tcp from any to any port {{ 80, 443 }} user {} keep state\n",
                a.user
            ));
            continue;
        }
        if let Some(t_port) = a.transparent_port {
            if t_port != a.proxy_port {
                out.push_str(&format!(
                    "pass out quick proto tcp from any to $proxy_ip port {{ {}, {} }} user {} keep state\n",
                    a.proxy_port, t_port, a.user
                ));
                continue;
            }
        }
        out.push_str(&format!(
            "pass out quick proto tcp from any to $proxy_ip port {} user {} keep state\n",
            a.proxy_port, a.user
        ));
    }

    out
}

pub fn generate_nftables_conf(
    proxy_ip: &str,
    dns_port: u16,
    agents: &[AgentFirewallRule],
    _control_port: u16,
) -> String {
    let mut users = vec![r#""_pa_daemon""#.to_string()];
    for a in agents {
        users.push(format!(r#""{}""#, a.user));
    }
    let users_set = users.join(", ");

    let mut out = format!(
        r#"flush ruleset

define PROXY_IP = {proxy_ip}
define DNS_PORT = {dns_port}

table ip pa_factory {{
    chain nat_output {{
        type nat hook output priority -100; policy accept;

        # Exclude loopback and direct proxy target
        ip daddr 127.0.0.0/8 return
        ip daddr $PROXY_IP return

        # Redirect all direct DNS traffic from agents to coding-agent-proxy DNS
        meta skuid >= 2001 udp dport 53 dnat to $PROXY_IP:$DNS_PORT
        meta skuid >= 2001 tcp dport 53 dnat to $PROXY_IP:$DNS_PORT

        # Redirect direct HTTP/HTTPS calls to transparent proxy ports
"#
    );

    for a in agents {
        let t_port = a.transparent_port.unwrap_or(a.proxy_port + 10);
        out.push_str(&format!(
            r#"        meta skuid "{}" tcp dport {{ 80, 443 }} dnat to $PROXY_IP:{}"#,
            a.user, t_port
        ));
        out.push('\n');
    }

    out.push_str(&format!(
        r#"    }}

    chain filter_output {{
        type filter hook output priority 0; policy drop;

        oifname "lo" accept
        ct state established,related accept

        # Allow DNS to proxy for all registered agent users
        meta skuid {{ {users_set} }} ip daddr $PROXY_IP udp dport $DNS_PORT accept
        meta skuid {{ {users_set} }} ip daddr $PROXY_IP tcp dport $DNS_PORT accept

        meta skuid "_pa_daemon" ip daddr $PROXY_IP tcp dport 8080 accept
"#
    ));

    for a in agents {
        if a.proxy_port == 0 {
            out.push_str(&format!(
                r#"        meta skuid "{}" tcp dport {{ 80, 443 }} accept{}"#,
                a.user, "\n"
            ));
            continue;
        }
        let t_port = a.transparent_port.unwrap_or(a.proxy_port + 10);
        if t_port != a.proxy_port {
            out.push_str(&format!(
                r#"        meta skuid "{}" ip daddr $PROXY_IP tcp dport {{ {}, {} }} accept{}"#,
                a.user, a.proxy_port, t_port, "\n"
            ));
        } else {
            out.push_str(&format!(
                r#"        meta skuid "{}" ip daddr $PROXY_IP tcp dport {} accept{}"#,
                a.user, a.proxy_port, "\n"
            ));
        }
    }

    out.push_str("    }\n}\n");
    out
}

pub fn apply_firewall(
    rules_content: &str,
    config_path: Option<&Path>,
    mock: bool,
) -> Result<PathBuf> {
    if mock && config_path.is_none() {
        let target = std::env::temp_dir().join("pa_mock_firewall.conf");
        fs::write(&target, rules_content)?;
        return Ok(target);
    }

    let target = match config_path {
        Some(p) => p.to_path_buf(),
        None => {
            if cfg!(target_os = "macos") {
                PathBuf::from("/etc/pf.conf")
            } else {
                PathBuf::from("/etc/nftables.conf")
            }
        }
    };

    if let Some(parent) = target.parent() {
        fs::create_dir_all(parent)?;
    }
    fs::write(&target, rules_content)?;

    if !mock {
        if cfg!(target_os = "macos") {
            let _ = Command::new("pfctl").arg("-e").output();
            let _ = Command::new("pfctl")
                .args(["-f", target.to_str().unwrap_or("")])
                .output();
        } else {
            let _ = Command::new("nft")
                .args(["-f", target.to_str().unwrap_or("")])
                .output();
        }
    }

    Ok(target)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_firewall_zero_port_rules() {
        let agents = vec![
            AgentFirewallRule {
                user: "lead-architect".to_string(),
                proxy_port: 0,
                transparent_port: None,
            },
            AgentFirewallRule {
                user: "test-runner".to_string(),
                proxy_port: 8082,
                transparent_port: Some(8092),
            },
        ];

        let pf = generate_pf_conf("192.168.64.1", 5353, &agents, 2222);
        assert!(pf.contains("pass out quick proto tcp from any to any port { 80, 443 } user lead-architect keep state"));
        assert!(pf.contains("pass out quick proto tcp from any to $proxy_ip port { 8082, 8092 } user test-runner keep state"));

        let nft = generate_nftables_conf("192.168.64.1", 5353, &agents, 2222);
        assert!(nft.contains(r#"meta skuid "lead-architect" tcp dport { 80, 443 } accept"#));
        assert!(nft.contains(
            r#"meta skuid "test-runner" ip daddr $PROXY_IP tcp dport { 8082, 8092 } accept"#
        ));
    }
}
