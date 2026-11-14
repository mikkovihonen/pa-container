use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

pub fn build_bwrap_args(
    user: &str,
    home_dir: &Path,
    proxy_ip: &str,
    proxy_port: u16,
    command: &[String],
    ca_cert_path: Option<&Path>,
    extra_env: Option<&BTreeMap<String, String>>,
    shared_packages_dir: Option<&Path>,
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
        "--setenv".into(),
        "SSL_CERT_FILE".into(),
        cert_path.to_str().unwrap_or("").into(),
        "--setenv".into(),
        "NODE_EXTRA_CA_CERTS".into(),
        cert_path.to_str().unwrap_or("").into(),
        "--setenv".into(),
        "REQUESTS_CA_BUNDLE".into(),
        cert_path.to_str().unwrap_or("").into(),
    ];

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

pub fn generate_seatbelt_profile(
    user: &str,
    proxy_ip: &str,
    proxy_port: u16,
    dns_port: u16,
    other_users: Option<&[&str]>,
    vault_path: Option<&str>,
) -> String {
    let mut denied_reads = Vec::new();
    let users = other_users.unwrap_or(&["admin"]);
    for u in users {
        denied_reads.push(format!("    (subpath \"/Users/{}\")", u));
    }
    let vault = vault_path.unwrap_or("/private/var/pa-vault");
    denied_reads.push(format!("    (subpath \"{}\")", vault));
    denied_reads.push("    (subpath \"/etc/pa/profiles\")".into());
    let denied_clause = denied_reads.join("\n");

    format!(
        r#";; PA-Container 2.0 Agent Seatbelt Profile: {user}
(version 1)
(allow default)

;; 1. Strict Network Lockdown
(deny network*)
(allow network-outbound (remote tcp "{proxy_ip}:{proxy_port}"))
(allow network-outbound (remote udp "{proxy_ip}:{dns_port}"))
(allow network-outbound (remote tcp "{proxy_ip}:{dns_port}"))
(allow network-outbound (remote unix-socket))
(allow network-inbound (local ip "localhost:*"))
(allow network-outbound (remote ip "localhost:*"))

;; 2. Cross-User & Vault Read Protection
(deny file-read*
{denied_clause})

;; 3. Filesystem Write Jail
(deny file-write*)
(allow file-write*
    (subpath "/Users/{user}")
    (subpath "/private/tmp/pa-{user}")
    (subpath "/private/var/folders")
    (literal "/dev/null")
    (literal "/dev/zero")
    (literal "/dev/random")
    (literal "/dev/urandom")
    (literal "/dev/dtracehelper"))

;; 4. Allow Paravirtualized Metal GPU, CoreML, and IOKit Compute Access
(allow iokit-open
    (iokit-user-client-class "AGXDeviceUserClient")
    (iokit-user-client-class "AGXSharedUserClient")
    (iokit-user-client-class "IOSurfaceRootUserClient")
    (iokit-user-client-class "AppleKeyStoreUserClient"))
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
        let args = build_bwrap_args("agent1", &home, "10.0.0.1", 8081, &cmd, None, None, None);
        assert_eq!(args[0], "bwrap");
        assert!(args.contains(&"HTTP_PROXY".to_string()));
        assert!(args.contains(&"http://10.0.0.1:8081".to_string()));
        assert!(args.contains(&"hello".to_string()));
    }

    #[test]
    fn test_generate_seatbelt_profile() {
        let profile = generate_seatbelt_profile("agent1", "192.168.64.1", 8081, 5353, None, None);
        assert!(profile.contains("Agent Seatbelt Profile: agent1"));
        assert!(profile.contains(r#"remote tcp "192.168.64.1:8081""#));
        assert!(profile.contains(r#"(subpath "/Users/admin")"#));
        assert!(profile.contains(r#"(subpath "/private/var/pa-vault")"#));
        assert!(profile.contains(r#"(subpath "/Users/agent1")"#));
    }

    #[test]
    fn test_build_sandbox_exec_command() {
        let profile = PathBuf::from("/etc/pa/profiles/agent1.sb");
        let cmd = vec!["echo".into(), "test".into()];
        let args = build_sandbox_exec_command(&profile, &cmd);
        assert_eq!(args, vec!["sandbox-exec", "-f", "/etc/pa/profiles/agent1.sb", "echo", "test"]);
    }
}
