use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

#[allow(clippy::too_many_arguments)]
pub fn build_bwrap_args(
    user: &str,
    home_dir: &Path,
    proxy_ip: &str,
    proxy_port: u16,
    command: &[String],
    ca_cert_path: Option<&Path>,
    extra_env: Option<&BTreeMap<String, String>>,
    shared_packages_dir: Option<&Path>,
    extra_ro_paths: Option<&[String]>,
    extra_rw_paths: Option<&[String]>,
    allow_gpu: bool,
) -> Vec<String> {
    let default_cert = PathBuf::from("/opt/pa/certs/mitmproxy-ca-cert.pem");
    let cert_path = ca_cert_path.unwrap_or(&default_cert);
    let default_pkg = PathBuf::from("/opt/pa");
    let pkg_dir = shared_packages_dir.unwrap_or(&default_pkg);
    let workspace_dir = home_dir.join("workspace");
    let work_dir = if workspace_dir.exists() {
        workspace_dir.to_str().unwrap_or("").to_string()
    } else {
        home_dir.to_str().unwrap_or("").to_string()
    };

    let proxy_url = format!("http://{}:{}", proxy_ip, proxy_port);

    let mut args: Vec<String> = vec![
        "bwrap".into(),
        "--unshare-pid".into(),
        "--unshare-ipc".into(),
        "--unshare-uts".into(),
        "--die-with-parent".into(),
        "--ro-bind".into(),
        "/usr".into(),
        "/usr".into(),
        "--ro-bind".into(),
        "/bin".into(),
        "/bin".into(),
        "--ro-bind-try".into(),
        "/lib".into(),
        "/lib".into(),
        "--ro-bind-try".into(),
        "/lib64".into(),
        "/lib64".into(),
        "--ro-bind-try".into(),
        "/etc/resolv.conf".into(),
        "/etc/resolv.conf".into(),
        "--ro-bind-try".into(),
        "/etc/pki".into(),
        "/etc/pki".into(),
        "--ro-bind-try".into(),
        "/etc/ssl".into(),
        "/etc/ssl".into(),
        "--ro-bind-try".into(),
        pkg_dir.to_str().unwrap_or("").into(),
        pkg_dir.to_str().unwrap_or("").into(),
        "--proc".into(),
        "/proc".into(),
        "--dev".into(),
        "/dev".into(),
    ];

    if allow_gpu {
        args.extend([
            "--dev-bind-try".into(),
            "/dev/dri".into(),
            "/dev/dri".into(),
            "--dev-bind-try".into(),
            "/dev/kfd".into(),
            "/dev/kfd".into(),
            "--dev-bind-try".into(),
            "/dev/nvidia0".into(),
            "/dev/nvidia0".into(),
            "--dev-bind-try".into(),
            "/dev/nvidiactl".into(),
            "/dev/nvidiactl".into(),
            "--dev-bind-try".into(),
            "/dev/nvidia-uvm".into(),
            "/dev/nvidia-uvm".into(),
        ]);
    }

    if let Some(ro) = extra_ro_paths {
        for p in ro {
            args.push("--ro-bind-try".into());
            args.push(p.clone());
            args.push(p.clone());
        }
    }

    if let Some(rw) = extra_rw_paths {
        for p in rw {
            args.push("--bind-try".into());
            args.push(p.clone());
            args.push(p.clone());
        }
    }

    args.extend([
        "--tmpfs".into(),
        "/tmp".into(),
        "--tmpfs".into(),
        "/run".into(),
        "--tmpfs".into(),
        "/home".into(),
        "--bind".into(),
        home_dir.to_str().unwrap_or("").into(),
        home_dir.to_str().unwrap_or("").into(),
        "--chdir".into(),
        work_dir,
        "--setenv".into(),
        "HOME".into(),
        home_dir.to_str().unwrap_or("").into(),
        "--setenv".into(),
        "USER".into(),
        user.into(),
    ]);

    if proxy_port > 0 {
        args.extend([
            "--setenv".into(),
            "HTTP_PROXY".into(),
            proxy_url.clone(),
            "--setenv".into(),
            "HTTPS_PROXY".into(),
            proxy_url.clone(),
            "--setenv".into(),
            "http_proxy".into(),
            proxy_url.clone(),
            "--setenv".into(),
            "https_proxy".into(),
            proxy_url,
        ]);
    }

    args.extend([
        "--setenv".into(),
        "SSL_CERT_FILE".into(),
        cert_path.to_str().unwrap_or("").into(),
        "--setenv".into(),
        "NODE_EXTRA_CA_CERTS".into(),
        cert_path.to_str().unwrap_or("").into(),
        "--setenv".into(),
        "REQUESTS_CA_BUNDLE".into(),
        cert_path.to_str().unwrap_or("").into(),
    ]);

    if let Some(env_map) = extra_env {
        for (k, v) in env_map {
            args.push("--setenv".into());
            args.push(k.clone());
            args.push(v.clone());
        }
    }

    args.extend_from_slice(command);
    args
}

pub fn build_landlock_command(
    command: &[String],
    rw_paths: &[PathBuf],
    ro_paths: Option<&[PathBuf]>,
    allow_tcp_connect: Option<&[String]>,
    helper_bin: Option<&Path>,
) -> Vec<String> {
    let default_helper = PathBuf::from("/opt/pa/bin/pa-landlock-run");
    let helper = helper_bin.unwrap_or(&default_helper);

    if !helper.is_file() {
        return command.to_vec();
    }

    let mut args: Vec<String> = vec![helper.to_str().unwrap_or("").into()];

    for p in rw_paths {
        args.push("--rw-path".into());
        args.push(p.to_str().unwrap_or("").into());
    }

    if let Some(paths) = ro_paths {
        for p in paths {
            args.push("--ro-path".into());
            args.push(p.to_str().unwrap_or("").into());
        }
    }

    if let Some(conns) = allow_tcp_connect {
        for c in conns {
            args.push("--allow-tcp-connect".into());
            args.push(c.clone());
        }
    }

    args.extend_from_slice(command);
    args
}

#[allow(clippy::too_many_arguments)]
pub fn generate_seatbelt_profile(
    user: &str,
    _proxy_ip: &str,
    proxy_port: u16,
    dns_port: u16,
    other_users: Option<&[&str]>,
    vault_path: Option<&str>,
    extra_write_paths: Option<&[String]>,
    allow_gpu: bool,
    denied_write_paths: Option<&[String]>,
) -> String {
    let mut denied_reads = Vec::new();
    let users = other_users.unwrap_or(&["admin"]);
    for u in users {
        denied_reads.push(format!("    (subpath \"/Users/{}\")", u));
    }
    if let Some(vault) = vault_path {
        denied_reads.push(format!("    (subpath \"{}\")", vault));
    }
    denied_reads.push("    (subpath \"/etc/pa/profiles\")".into());
    let denied_clause = denied_reads.join("\n");

    let mut allowed_writes = vec![
        format!("    (subpath \"/Users/{}\")", user),
        format!("    (subpath \"/private/tmp/pa-{}\")", user),
        "    (subpath \"/private/var/folders\")".into(),
        "    (subpath \"/private/var/pa-vault\")".into(),
        "    (subpath \"/var/pa-vault\")".into(),
        "    (literal \"/dev/null\")".into(),
        "    (literal \"/dev/zero\")".into(),
        "    (literal \"/dev/random\")".into(),
        "    (literal \"/dev/urandom\")".into(),
        "    (literal \"/dev/dtracehelper\")".into(),
    ];
    if let Some(extras) = extra_write_paths {
        for p in extras {
            allowed_writes.push(format!("    (subpath \"{}\")", p));
        }
    }
    let allowed_writes_clause = allowed_writes.join("\n");

    let locked_clause = if let Some(locked) = denied_write_paths {
        let entries: Vec<String> = locked
            .iter()
            .map(|p| format!("    (subpath \"{}\")", p))
            .collect();
        if entries.is_empty() {
            String::new()
        } else {
            format!(
                "\n;; 3b. Anti-Tamper Test Assertion Locking (Read-Only Test Suite)\n(deny file-write*\n{})\n",
                entries.join("\n")
            )
        }
    } else {
        String::new()
    };

    let gpu_clause = if allow_gpu {
        r#";; 4. Allow Paravirtualized Metal GPU, CoreML, and IOKit Compute Access
(allow iokit-open
    (iokit-user-client-class "AGXDeviceUserClient")
    (iokit-user-client-class "AGXSharedUserClient")
    (iokit-user-client-class "IOSurfaceRootUserClient")
    (iokit-user-client-class "AppleKeyStoreUserClient"))"#
    } else {
        ";; 4. GPU Access Disabled"
    };

    let proxy_clause = if proxy_port > 0 {
        format!(r#"(allow network-outbound (remote tcp "*:{proxy_port}"))"#)
    } else {
        r#"(allow network-outbound (remote tcp "*:80"))
(allow network-outbound (remote tcp "*:443"))"#
            .to_string()
    };

    format!(
        r#";; PA-Container 2.0 Agent Seatbelt Profile: {user}
(version 1)
(allow default)

;; 1. Strict Network Lockdown
(deny network*)
{proxy_clause}
(allow network-outbound (remote udp "*:{dns_port}"))
(allow network-outbound (remote tcp "*:{dns_port}"))
(allow network-outbound (remote unix-socket))
(allow network-inbound (local ip "localhost:*"))
(allow network-outbound (remote ip "localhost:*"))

;; 2. Cross-User & Vault Read Protection
(deny file-read*
{denied_clause})

;; 3. Filesystem Write Jail
(deny file-write*)
(allow file-write*
{allowed_writes_clause}){locked_clause}

{gpu_clause}
"#
    )
}

pub fn build_sandbox_exec_command(profile_path: &Path, command: &[String]) -> Vec<String> {
    let mut args = vec![
        "sandbox-exec".into(),
        "-f".into(),
        profile_path.to_str().unwrap_or("").into(),
    ];
    args.extend_from_slice(command);
    args
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_build_bwrap_args() {
        let home = PathBuf::from("/home/agent1");
        let cmd = vec!["pi".into(), "-p".into(), "hello".into()];
        let ro = vec!["/opt/ro".to_string()];
        let rw = vec!["/opt/rw".to_string()];
        let args = build_bwrap_args(
            "agent1",
            &home,
            "10.0.0.1",
            8081,
            &cmd,
            None,
            None,
            None,
            Some(&ro),
            Some(&rw),
            true,
        );
        assert_eq!(args[0], "bwrap");
        assert!(args.contains(&"HTTP_PROXY".to_string()));
        assert!(args.contains(&"http://10.0.0.1:8081".to_string()));
        assert!(args.contains(&"hello".to_string()));
        assert!(args.contains(&"/opt/ro".to_string()));
        assert!(args.contains(&"/opt/rw".to_string()));
        assert!(args.contains(&"/dev/dri".to_string()));
    }

    #[test]
    fn test_build_bwrap_args_transparent_zero_port() {
        let home = PathBuf::from("/home/agent1");
        let cmd = vec!["pi".into(), "-p".into(), "hello".into()];
        let args = build_bwrap_args(
            "agent1", &home, "10.0.0.1", 0, &cmd, None, None, None, None, None, false,
        );
        assert_eq!(args[0], "bwrap");
        assert!(!args.contains(&"HTTP_PROXY".to_string()));
        assert!(!args.contains(&"HTTPS_PROXY".to_string()));
        assert!(args.contains(&"SSL_CERT_FILE".to_string()));
    }

    #[test]
    fn test_generate_seatbelt_profile_transparent_zero_port() {
        let profile = generate_seatbelt_profile(
            "agent1",
            "192.168.64.1",
            0,
            5353,
            None,
            None,
            None,
            false,
            None,
        );
        assert!(profile.contains("Agent Seatbelt Profile: agent1"));
        assert!(!profile.contains("remote tcp \"192.168.64.1:0\""));
        assert!(profile.contains(r#"(allow network-outbound (remote tcp "*:80"))"#));
        assert!(profile.contains(r#"(allow network-outbound (remote tcp "*:443"))"#));
    }

    #[test]
    fn test_generate_seatbelt_profile() {
        let extras = vec!["/opt/pa/extra".to_string()];
        let profile = generate_seatbelt_profile(
            "agent1",
            "192.168.64.1",
            8081,
            5353,
            None,
            Some("/custom/vault"),
            Some(&extras),
            true,
            None,
        );
        assert!(profile.contains("Agent Seatbelt Profile: agent1"));
        assert!(profile.contains(r#"remote tcp "*:8081""#));
        assert!(profile.contains(r#"(subpath "/Users/admin")"#));
        assert!(profile.contains(r#"(subpath "/custom/vault")"#));
        assert!(profile.contains(r#"(subpath "/Users/agent1")"#));
        assert!(profile.contains(r#"(subpath "/opt/pa/extra")"#));
        assert!(profile.contains("AGXDeviceUserClient"));
    }

    #[test]
    fn test_generate_seatbelt_profile_assertion_locking() {
        let locked_tests = vec!["/Users/pa-coder/workspace/tests".to_string()];
        let profile = generate_seatbelt_profile(
            "pa-coder",
            "192.168.64.1",
            8081,
            5353,
            None,
            None,
            None,
            false,
            Some(&locked_tests),
        );
        assert!(profile.contains("Anti-Tamper Test Assertion Locking"));
        assert!(profile.contains(r#"(deny file-write*"#));
        assert!(profile.contains(r#"(subpath "/Users/pa-coder/workspace/tests")"#));
    }

    #[test]
    fn test_build_sandbox_exec_command() {
        let profile = PathBuf::from("/etc/pa/profiles/agent1.sb");
        let cmd = vec!["echo".into(), "test".into()];
        let args = build_sandbox_exec_command(&profile, &cmd);
        assert_eq!(
            args,
            vec![
                "sandbox-exec",
                "-f",
                "/etc/pa/profiles/agent1.sb",
                "echo",
                "test"
            ]
        );
    }
}
