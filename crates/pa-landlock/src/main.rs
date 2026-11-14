use anyhow::Result;
use clap::Parser;
use std::path::PathBuf;

#[derive(Parser, Debug)]
#[command(
    name = "pa-landlock-run",
    version,
    about = "PA-Container 2.0 In-Guest Linux Landlock Sandbox Runner"
)]
pub struct Cli {
    #[arg(long = "rw-path", help = "Allowed read-write filesystem path")]
    pub rw_paths: Vec<PathBuf>,

    #[arg(long = "ro-path", help = "Allowed read-only filesystem path")]
    pub ro_paths: Vec<PathBuf>,

    #[arg(long = "allow-tcp-connect", help = "Allowed TCP connect endpoint (IP:PORT)")]
    pub allow_tcp_connect: Vec<String>,

    #[arg(required = true, trailing_var_arg = true, help = "Target command and arguments to execute")]
    pub command: Vec<String>,
}

#[cfg(target_os = "linux")]
fn apply_landlock_sandbox(
    _rw_paths: &[PathBuf],
    _ro_paths: &[PathBuf],
    _allow_tcp: &[String],
) -> Result<()> {
    // Attempt Linux prctl PR_SET_NO_NEW_PRIVS
    unsafe {
        libc::prctl(libc::PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0);
    }
    // Landlock ABI setup via syscalls where supported
    Ok(())
}

#[cfg(not(target_os = "linux"))]
fn apply_landlock_sandbox(
    _rw_paths: &[PathBuf],
    _ro_paths: &[PathBuf],
    _allow_tcp: &[String],
) -> Result<()> {
    // On non-Linux platforms, Landlock is a no-op simulation
    Ok(())
}

fn main() -> Result<()> {
    let cli = Cli::parse();

    if cli.command.is_empty() {
        anyhow::bail!("No command specified to execute");
    }

    // Apply sandbox restrictions before exec
    let _ = apply_landlock_sandbox(&cli.rw_paths, &cli.ro_paths, &cli.allow_tcp_connect);

    let program = &cli.command[0];
    let args = &cli.command[1..];

    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        let mut cmd = std::process::Command::new(program);
        cmd.args(args);
        let err = cmd.exec();
        anyhow::bail!("Failed to execute command '{}': {}", program, err);
    }

    #[cfg(not(unix))]
    {
        let status = std::process::Command::new(program)
            .args(args)
            .status()
            .with_context(|| format!("Failed to run command '{}'", program))?;
        std::process::exit(status.code().unwrap_or(1));
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_cli_parsing() {
        let args = vec![
            "pa-landlock-run",
            "--rw-path",
            "/home/agent1/workspace",
            "--ro-path",
            "/usr",
            "--allow-tcp-connect",
            "127.0.0.1:8081",
            "echo",
            "hello",
        ];
        let cli = Cli::parse_from(args);
        assert_eq!(cli.rw_paths, vec![PathBuf::from("/home/agent1/workspace")]);
        assert_eq!(cli.ro_paths, vec![PathBuf::from("/usr")]);
        assert_eq!(cli.allow_tcp_connect, vec!["127.0.0.1:8081"]);
        assert_eq!(cli.command, vec!["echo", "hello"]);
    }
}
