use anyhow::Result;
use clap::{Args, Parser, Subcommand};
use pa_core::backend::get_backend;
use pa_core::review::review_agent_workspace;
use pa_core::schema::{load_factory_config, resolve_agent_ports, AgentSpec};
use serde_json::json;
use std::path::PathBuf;

#[derive(Parser, Debug)]
#[command(
    name = "pa",
    version,
    about = "PA-Container 2.0: Next-Generation Agentic Software Factory"
)]
pub struct Cli {
    #[arg(short, long, help = "Verbose logging output")]
    pub verbose: bool,

    #[arg(short, long, help = "Suppress normal stdout messages")]
    pub quiet: bool,

    #[command(subcommand)]
    pub command: Commands,
}

#[derive(Subcommand, Debug)]
pub enum Commands {
    #[command(about = "Launch an agent in the Software Factory environment")]
    Run(RunArgs),

    #[command(about = "Manage the Software Factory VM lifecycle")]
    Factory(FactoryArgs),

    #[command(about = "Review an agent's workspace in a local Git worktree")]
    Review(ReviewArgs),

    #[command(about = "Inspect or open the multi-agent network proxy and port table")]
    Proxy(ProxyArgs),

    #[command(about = "Inspect agent execution and network flow logs")]
    Logs(LogsArgs),
}

#[derive(Args, Debug)]
pub struct RunArgs {
    #[arg(short, long, help = "ID of the agent to launch (e.g. agent1)")]
    pub agent: Option<String>,

    #[arg(short, long, help = "Initial prompt / task instructions for the agent")]
    pub prompt: Option<String>,

    #[arg(short, long, help = "Path to factory.toml configuration file")]
    pub config: Option<PathBuf>,

    #[arg(trailing_var_arg = true, help = "Extra arguments passed to the agent driver")]
    pub extra_args: Vec<String>,
}

#[derive(Args, Debug)]
pub struct FactoryArgs {
    #[arg(help = "Factory lifecycle action: up, down, or status", default_value = "status")]
    pub action: String,

    #[arg(short, long, help = "Path to factory.toml configuration file")]
    pub config: Option<PathBuf>,
}

#[derive(Args, Debug)]
pub struct ReviewArgs {
    #[arg(help = "ID of the agent to review", default_value = "agent1")]
    pub agent: String,

    #[arg(long, help = "Open the review worktree in your IDE")]
    pub open: bool,

    #[arg(long, help = "Custom IDE command (e.g. 'code', 'cursor', 'zed')")]
    pub ide: Option<String>,
}

#[derive(Args, Debug)]
pub struct ProxyArgs {
    #[arg(long, help = "Show all agents and policies")]
    pub all: bool,

    #[arg(long, help = "Open proxy web interface in browser")]
    pub open: bool,

    #[arg(long, help = "Print web UI URL")]
    pub url: bool,

    #[arg(long, help = "Output proxy port mapping as JSON")]
    pub json: bool,

    #[arg(short, long, help = "Path to factory.toml configuration file")]
    pub config: Option<PathBuf>,
}

#[derive(Args, Debug)]
pub struct LogsArgs {
    #[arg(short, long, help = "Filter logs to specific agent ID")]
    pub agent: Option<String>,

    #[arg(short, long, help = "Follow log stream")]
    pub follow: bool,

    #[arg(short = 'n', long, help = "Number of lines to show")]
    pub lines: Option<usize>,
}

fn handle_run(args: &RunArgs) -> Result<()> {
    let config = load_factory_config(args.config.as_deref())?;
    let resolved_agents = resolve_agent_ports(&config.agents, false);

    let target_agent_id = args.agent.as_deref().unwrap_or_else(|| {
        resolved_agents
            .first()
            .map(|a| a.id.as_str())
            .unwrap_or("agent1")
    });

    let target_agent = resolved_agents
        .iter()
        .find(|a| a.id == target_agent_id)
        .cloned()
        .unwrap_or_else(|| AgentSpec::new(target_agent_id));

    println!(
        "==> Starting Software Factory for agent '{}' (driver: {})...",
        target_agent.id, target_agent.driver
    );

    let backend = get_backend(&config)?;
    let proxy_ip = backend.start_proxy(&config)?;
    println!("==> Proxy listening at gateway {}", proxy_ip);

    backend.ensure_factory_vm(&config, &proxy_ip)?;
    println!("==> Factory VM is ready.");

    let cwd = std::env::current_dir()?;
    let commit = backend.sync_git_to_vault(&cwd, "HEAD")?;
    println!("==> Synced repository to Vault at commit {}.", commit);

    let exit_code = backend.launch_agent(&target_agent, args.prompt.as_deref())?;
    println!(
        "==> Agent '{}' started (exit code: {}).",
        target_agent.id, exit_code
    );

    Ok(())
}

fn handle_factory(args: &FactoryArgs) -> Result<()> {
    let config = load_factory_config(args.config.as_deref())?;
    let backend = get_backend(&config)?;

    match args.action.to_lowercase().as_str() {
        "up" => {
            println!("==> Bringing up Software Factory VM and proxy...");
            let proxy_ip = backend.start_proxy(&config)?;
            backend.ensure_factory_vm(&config, &proxy_ip)?;
            println!("==> Software Factory is UP (Proxy gateway: {}).", proxy_ip);
        }
        "down" => {
            println!("==> Shutting down Software Factory VM and stopping processes...");
            backend.stop_factory()?;
            println!("==> Software Factory is DOWN.");
        }
        "status" => {
            let status = backend.get_status()?;
            println!("{}", serde_json::to_string_pretty(&status)?);
        }
        other => {
            anyhow::bail!("Unknown factory action '{}'. Expected 'up', 'down', or 'status'.", other);
        }
    }

    Ok(())
}

fn handle_review(args: &ReviewArgs) -> Result<()> {
    println!("==> Preparing review worktree for agent '{}'...", args.agent);
    let worktree_path = review_agent_workspace(
        &args.agent,
        None,
        args.open,
        args.ide.as_deref(),
        false,
    )?;
    println!("==> Review worktree ready at: {}", worktree_path.display());
    Ok(())
}

fn handle_proxy(args: &ProxyArgs) -> Result<()> {
    let config = load_factory_config(args.config.as_deref())?;
    let agents = resolve_agent_ports(&config.agents, false);

    if args.url {
        println!("http://127.0.0.1:8081");
        return Ok(());
    }

    if args.open {
        let _ = open_in_browser("http://127.0.0.1:8081");
        return Ok(());
    }

    if args.json {
        let list: Vec<_> = agents
            .iter()
            .map(|a| {
                json!({
                    "id": a.id,
                    "uid": a.uid,
                    "driver": a.driver,
                    "proxy_port": a.proxy_port,
                    "transparent_port": a.transparent_port,
                    "allowlist": a.allowlist,
                    "tokens": a.tokens,
                })
            })
            .collect();
        println!("{}", serde_json::to_string_pretty(&list)?);
        return Ok(());
    }

    println!("{:<15} {:<8} {:<10} {:<12} {:<18} {:<15}", "AGENT ID", "UID", "DRIVER", "PROXY PORT", "TRANSPARENT PORT", "ALLOWLIST");
    println!("{}", "-".repeat(82));
    for a in &agents {
        let p_port = a.proxy_port.map(|p| p.to_string()).unwrap_or_else(|| "-".into());
        let t_port = a.transparent_port.map(|p| p.to_string()).unwrap_or_else(|| "-".into());
        let allowed = if a.allowlist.is_empty() {
            "*".to_string()
        } else {
            a.allowlist.join(",")
        };
        println!(
            "{:<15} {:<8} {:<10} {:<12} {:<18} {:<15}",
            a.id, a.uid, a.driver, p_port, t_port, allowed
        );
    }

    Ok(())
}

fn handle_logs(args: &LogsArgs) -> Result<()> {
    let agent_id = args.agent.as_deref().unwrap_or("agent1");
    let cache_dir = dirs_fallback_cache();
    let flow_file = cache_dir.join(format!("flows-agent-{}.jsonl", agent_id));

    println!("==> Reading logs for agent '{}' from {}...", agent_id, flow_file.display());

    if flow_file.is_file() {
        let content = std::fs::read_to_string(&flow_file)?;
        let lines: Vec<&str> = content.lines().collect();
        let count = args.lines.unwrap_or(lines.len()).min(lines.len());
        for line in &lines[lines.len() - count..] {
            println!("{}", line);
        }
    } else {
        println!("(No log entries recorded yet for agent '{}')", agent_id);
    }

    Ok(())
}

fn open_in_browser(url: &str) -> Result<()> {
    #[cfg(target_os = "macos")]
    {
        std::process::Command::new("open").arg(url).spawn()?;
    }
    #[cfg(target_os = "linux")]
    {
        std::process::Command::new("xdg-open").arg(url).spawn()?;
    }
    Ok(())
}

fn dirs_fallback_cache() -> PathBuf {
    if let Ok(home) = std::env::var("HOME") {
        PathBuf::from(home).join(".cache").join("pa-container")
    } else {
        std::env::temp_dir().join("pa-container")
    }
}

fn main() -> Result<()> {
    let cli = Cli::parse();

    match &cli.command {
        Commands::Run(args) => handle_run(args),
        Commands::Factory(args) => handle_factory(args),
        Commands::Review(args) => handle_review(args),
        Commands::Proxy(args) => handle_proxy(args),
        Commands::Logs(args) => handle_logs(args),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_cli_parsing_run() {
        let args = vec!["pa", "run", "--agent", "lead-agent", "--prompt", "do work"];
        let cli = Cli::parse_from(args);
        match cli.command {
            Commands::Run(r) => {
                assert_eq!(r.agent.as_deref(), Some("lead-agent"));
                assert_eq!(r.prompt.as_deref(), Some("do work"));
            }
            _ => panic!("Expected Run command"),
        }
    }

    #[test]
    fn test_cli_parsing_proxy() {
        let args = vec!["pa", "proxy", "--json"];
        let cli = Cli::parse_from(args);
        match cli.command {
            Commands::Proxy(p) => {
                assert!(p.json);
            }
            _ => panic!("Expected Proxy command"),
        }
    }

    #[test]
    fn test_cli_parsing_review() {
        let args = vec!["pa", "review", "agent2", "--open"];
        let cli = Cli::parse_from(args);
        match cli.command {
            Commands::Review(r) => {
                assert_eq!(r.agent, "agent2");
                assert!(r.open);
            }
            _ => panic!("Expected Review command"),
        }
    }
}
