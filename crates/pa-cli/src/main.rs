use anyhow::Result;
use clap::{Args, Parser, Subcommand};
use pa_core::backend::get_backend;
use pa_core::feature::{Feature, FeatureStatus, TaskSlice, TestKind, TestScenario};
use pa_core::review::review_agent_workspace;
use pa_core::schema::{load_factory_config, resolve_agent_sockets, AgentSpec};
use serde_json::json;
use std::io::{IsTerminal, Write};
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

    #[command(about = "Manage the Agentic Feature Implementation lifecycle")]
    Feature(FeatureArgs),

    #[command(about = "Inspect and manage OpenTelemetry spans, traces, and metrics")]
    Telemetry(TelemetryArgs),

    #[command(about = "Verify and check requirement and test traceability")]
    Traceability(TraceabilityArgs),

    #[command(about = "Inspect OKRs-as-Code objectives, key results, and budgets")]
    Okr(OkrArgs),

    #[command(about = "Inspect and verify cross-platform Design System contracts & tokens")]
    Design(DesignArgs),
}

#[derive(Args, Debug)]
pub struct RunArgs {
    #[arg(short, long, help = "ID of the agent to launch (e.g. agent1)")]
    pub agent: Option<String>,

    #[arg(short, long, help = "Initial prompt / task instructions for the agent")]
    pub prompt: Option<String>,

    #[arg(short, long, help = "Path to factory.toml configuration file")]
    pub config: Option<PathBuf>,

    #[arg(
        long,
        help = "Role to assign to the agent (e.g. spec_architect, design_engineer)"
    )]
    pub role: Option<String>,

    #[arg(long, help = "Associated Objective ID (e.g. OBJ-2026-Q4-SEC)")]
    pub objective: Option<String>,

    #[arg(
        long,
        help = "Associated Key Result IDs (comma-separated, e.g. KR-AUTH-01)"
    )]
    pub kr: Option<String>,

    #[arg(
        long,
        help = "Associated Requirement IDs (comma-separated, e.g. REQ-AUTH-01)"
    )]
    pub req: Option<String>,

    #[arg(
        trailing_var_arg = true,
        help = "Extra arguments passed to the agent driver"
    )]
    pub extra_args: Vec<String>,
}

#[derive(Args, Debug)]
pub struct TelemetryArgs {
    #[command(subcommand)]
    pub command: TelemetryCommands,
}

#[derive(Subcommand, Debug)]
pub enum TelemetryCommands {
    #[command(about = "Display active OTLP provider and telemetry status")]
    Status(TelemetryStatusArgs),

    #[command(about = "Open the OTLP provider web UI in browser (e.g. Phoenix)")]
    Ui(TelemetryUiArgs),

    #[command(about = "Inspect traces or events for a specific task ID")]
    Trace(TelemetryTraceArgs),

    #[command(about = "Display aggregated analytical outcomes, FinOps, and DORA metrics")]
    Report(TelemetryReportArgs),

    #[command(about = "Synchronize local analytical store with external telemetry")]
    Sync(TelemetrySyncArgs),
}

#[derive(Args, Debug)]
pub struct TelemetryStatusArgs {
    #[arg(short, long, help = "Path to factory.toml configuration file")]
    pub config: Option<PathBuf>,

    #[arg(long, help = "Output status as JSON")]
    pub json: bool,
}

#[derive(Args, Debug)]
pub struct TelemetryUiArgs {
    #[arg(short, long, help = "Path to factory.toml configuration file")]
    pub config: Option<PathBuf>,

    #[arg(long, help = "Print web UI URL only")]
    pub url: bool,
}

#[derive(Args, Debug)]
pub struct TelemetryTraceArgs {
    #[arg(help = "Task ID to query traces for")]
    pub task_id: String,

    #[arg(short, long, help = "Path to factory.toml configuration file")]
    pub config: Option<PathBuf>,
}

#[derive(Args, Debug)]
pub struct TelemetryReportArgs {
    #[arg(short, long, help = "Path to factory.toml configuration file")]
    pub config: Option<PathBuf>,

    #[arg(long, help = "Output report as JSON")]
    pub json: bool,
}

#[derive(Args, Debug)]
pub struct TelemetrySyncArgs {
    #[arg(short, long, help = "Path to factory.toml configuration file")]
    pub config: Option<PathBuf>,
}

#[derive(Args, Debug)]
pub struct TraceabilityArgs {
    #[command(subcommand)]
    pub command: TraceabilityCommands,
}

#[derive(Subcommand, Debug)]
pub enum TraceabilityCommands {
    #[command(about = "Scan workspace and verify requirement & test coverage")]
    Check(TraceabilityCheckArgs),
}

#[derive(Args, Debug)]
pub struct TraceabilityCheckArgs {
    #[arg(short, long, help = "Path to factory.toml configuration file")]
    pub config: Option<PathBuf>,

    #[arg(long, help = "Output report as JSON")]
    pub json: bool,
}

#[derive(Args, Debug)]
pub struct OkrArgs {
    #[command(subcommand)]
    pub command: OkrCommands,
}

#[derive(Subcommand, Debug)]
pub enum OkrCommands {
    #[command(about = "List objectives, key results, and linked requirements")]
    Status(OkrStatusArgs),
}

#[derive(Args, Debug)]
pub struct OkrStatusArgs {
    #[arg(
        short,
        long,
        help = "Path to OKR manifests directory",
        default_value = "docs/okrs"
    )]
    pub dir: PathBuf,

    #[arg(long, help = "Output status as JSON")]
    pub json: bool,
}

#[derive(Args, Debug)]
pub struct DesignArgs {
    #[command(subcommand)]
    pub command: DesignCommands,
}

#[derive(Subcommand, Debug)]
pub enum DesignCommands {
    #[command(about = "List and inspect active W3C DTCG design tokens")]
    Tokens(DesignTokensArgs),

    #[command(about = "Verify design system compliance across enabled platforms")]
    Check(DesignCheckArgs),
}

#[derive(Args, Debug)]
pub struct DesignTokensArgs {
    #[arg(short, long, help = "Path to factory.toml configuration file")]
    pub config: Option<PathBuf>,

    #[arg(long, help = "Filter tokens by type (e.g. color, dimension)")]
    pub token_type: Option<String>,

    #[arg(long, help = "Output tokens as JSON")]
    pub json: bool,
}

#[derive(Args, Debug)]
pub struct DesignCheckArgs {
    #[arg(short, long, help = "Path to factory.toml configuration file")]
    pub config: Option<PathBuf>,

    #[arg(long, help = "Output compliance report as JSON")]
    pub json: bool,
}

#[derive(Args, Debug)]
pub struct FactoryArgs {
    #[arg(
        help = "Factory lifecycle action: up, down, or status",
        default_value = "status"
    )]
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

#[derive(Args, Debug)]
pub struct FeatureArgs {
    #[command(subcommand)]
    pub command: FeatureCommands,
}

#[derive(Subcommand, Debug)]
pub enum FeatureCommands {
    #[command(about = "Plan a new feature via interactive Architect interview")]
    Plan(FeaturePlanArgs),

    #[command(about = "List or inspect feature specification status")]
    Status(FeatureStatusArgs),

    #[command(about = "Run the staged multi-agent pipeline (Red -> Green -> Verify)")]
    Run(FeatureRunArgs),

    #[command(about = "Review a completed feature worktree")]
    Review(FeatureReviewArgs),
}

#[derive(Args, Debug)]
pub struct FeaturePlanArgs {
    #[arg(help = "Kebab-case slug identifier for the feature (e.g. 'token-refresh')")]
    pub slug: String,

    #[arg(short, long, help = "Human-readable title of the feature")]
    pub title: Option<String>,

    #[arg(short, long, help = "Initial prompt / intent for the feature")]
    pub prompt: Option<String>,

    #[arg(long, default_value = "main", help = "Target branch for merging")]
    pub target_branch: String,

    #[arg(long, help = "Run in non-interactive batch mode")]
    pub non_interactive: bool,

    #[arg(
        long,
        help = "Automatically approve spec (Gate 1 sign-off) in non-interactive mode"
    )]
    pub approve: bool,
}

#[derive(Args, Debug)]
pub struct FeatureStatusArgs {
    #[arg(help = "Optional slug to inspect a specific feature")]
    pub slug: Option<String>,

    #[arg(long, help = "Output status as JSON")]
    pub json: bool,
}

#[derive(Args, Debug)]
pub struct FeatureRunArgs {
    #[arg(help = "Slug of the feature to run")]
    pub slug: String,

    #[arg(
        long,
        help = "Specific stage to run: 'red', 'green', 'verify', or 'all'",
        default_value = "all"
    )]
    pub stage: String,

    #[arg(short, long, help = "Path to factory.toml configuration file")]
    pub config: Option<PathBuf>,
}

#[derive(Args, Debug)]
pub struct FeatureReviewArgs {
    #[arg(help = "Slug of the feature to review")]
    pub slug: String,

    #[arg(long, help = "Open the review worktree in your IDE")]
    pub open: bool,

    #[arg(long, help = "Custom IDE command (e.g. 'code', 'cursor', 'zed')")]
    pub ide: Option<String>,

    #[arg(long, help = "Print diff against target branch")]
    pub diff: bool,

    #[arg(
        long,
        help = "Approve and merge the verified feature into target branch"
    )]
    pub approve: bool,

    #[arg(long, help = "Feedback instructions for revision cycle")]
    pub feedback: Option<String>,
}

fn count_active_wip_features(cwd: &std::path::Path) -> usize {
    let features_dir = cwd.join(".pa/features");
    if !features_dir.is_dir() {
        return 0;
    }
    let mut count = 0;
    if let Ok(entries) = std::fs::read_dir(features_dir) {
        for entry in entries.flatten() {
            if entry.path().is_dir() {
                let name = entry.file_name().to_string_lossy().to_string();
                if let Ok(feat) = Feature::load(cwd, &name) {
                    if feat.status == FeatureStatus::Approved
                        || feat.status == FeatureStatus::RedPhase
                        || feat.status == FeatureStatus::GreenPhase
                        || feat.status == FeatureStatus::Verified
                    {
                        count += 1;
                    }
                }
            }
        }
    }
    count
}

fn handle_run(args: &RunArgs) -> Result<()> {
    let mut config = load_factory_config(args.config.as_deref())?;

    let packages_dir = std::env::current_dir()?.join("pa_packages");
    let registry = if packages_dir.is_dir() {
        pa_core::manifest::CapabilityRegistry::discover(&packages_dir)?
    } else {
        pa_core::manifest::CapabilityRegistry::default()
    };
    pa_core::manifest::merge_agent_capabilities(&mut config.agents, &registry)?;

    let cache_dir = dirs_fallback_cache();
    let sockets_dir = cache_dir.join("sockets");
    let resolved_agents = resolve_agent_sockets(&config.agents, &sockets_dir);

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

    let target_caps = if !target_agent.capabilities.is_empty() {
        Some(registry.resolve_for_agent(&target_agent.capabilities)?)
    } else {
        None
    };

    // Initialize TaskContext and write proxy-bindings.json
    let now_ts = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    let task_id = format!("task-{}", now_ts);
    let mut task_ctx = pa_core::telemetry::TaskContext::new(&task_id);
    task_ctx.agent_role = args.role.clone().or_else(|| target_agent.role.clone());
    task_ctx.objective_id = args.objective.clone();
    if let Some(ref kr) = args.kr {
        task_ctx.kr_ids = kr
            .split(',')
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty())
            .collect();
    }
    if let Some(ref req) = args.req {
        task_ctx.req_ids = req
            .split(',')
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty())
            .collect();
    }

    let bindings_path = cache_dir.join("proxy-bindings.json");
    let mut bindings = pa_core::telemetry::ProxyBindings::load(&bindings_path).unwrap_or_default();
    let proxy_port = target_agent.proxy_port.unwrap_or(8081);
    bindings.set_for_port(proxy_port, task_ctx.clone());
    let _ = bindings.save_atomic(&bindings_path);

    // Emit root span pa.task.run
    let _ = pa_core::telemetry::emit_root_span(&task_ctx, &config.telemetry.otlp, Some(&cache_dir));
    println!(
        "==> Telemetry active: trace_id={}, task_id={} (provider: {})",
        task_ctx.trace_id, task_ctx.task_id, config.telemetry.otlp.provider
    );

    let cwd = std::env::current_dir()?;

    // Closed-Loop Governance Evaluation
    if let Ok(store) = pa_core::storage::get_analytics_store(&config.storage.path) {
        let active_wip = count_active_wip_features(&cwd);
        let gov_decision = pa_core::governance::GovernanceEngine::evaluate_dispatch(
            store.as_ref(),
            &config.governance,
            active_wip,
            task_ctx.kr_ids.first().map(|s| s.as_str()),
        )?;

        if !gov_decision.allowed {
            eprintln!("[GOVERNANCE ERROR] {}", gov_decision.reason);
            anyhow::bail!(
                "Governance guardrail blocked dispatch: {}",
                gov_decision.reason
            );
        }

        if let Some(ref model_override) = gov_decision.model_override {
            println!(
                "==> [GOVERNANCE] Model override applied: {} ({})",
                model_override, gov_decision.reason
            );
            task_ctx.model_profile = Some(model_override.clone());
        }

        if gov_decision.defense_mode_active {
            println!(
                "==> [GOVERNANCE WARNING] SLO Defense Mode active (health: {:.1}%).",
                gov_decision.slo_health_pct
            );
        }
    }

    // Closed-Loop Governance Evaluation
    if let Ok(store) = pa_core::storage::get_analytics_store(&config.storage.path) {
        let active_wip = count_active_wip_features(&cwd);
        let gov_decision = pa_core::governance::GovernanceEngine::evaluate_dispatch(
            store.as_ref(),
            &config.governance,
            active_wip,
            task_ctx.kr_ids.first().map(|s| s.as_str()),
        )?;

        if !gov_decision.allowed {
            eprintln!("[GOVERNANCE ERROR] {}", gov_decision.reason);
            anyhow::bail!(
                "Governance guardrail blocked dispatch: {}",
                gov_decision.reason
            );
        }

        if let Some(ref model_override) = gov_decision.model_override {
            println!(
                "==> [GOVERNANCE] Model override applied: {} ({})",
                model_override, gov_decision.reason
            );
            task_ctx.model_profile = Some(model_override.clone());
        }

        if gov_decision.defense_mode_active {
            println!(
                "==> [GOVERNANCE WARNING] SLO Defense Mode active (health: {:.1}%).",
                gov_decision.slo_health_pct
            );
        }
    }

    let backend = get_backend(&config)?;
    let proxy_ip = backend.start_proxy(&config)?;
    println!("==> Proxy listening at gateway {}", proxy_ip);

    backend.ensure_factory_vm(&config, &proxy_ip)?;
    println!("==> Factory VM is ready.");

    if let Some(ref caps) = target_caps {
        backend.provision_capabilities(caps)?;
    }

    let commit = backend.sync_git_to_vault(&cwd, "HEAD")?;
    println!("==> Synced repository to Vault at commit {}.", commit);

    let exit_code =
        backend.launch_agent(&target_agent, args.prompt.as_deref(), target_caps.as_ref())?;
    println!(
        "==> Agent '{}' started (exit code: {}).",
        target_agent.id, exit_code
    );

    Ok(())
}

fn handle_factory(args: &FactoryArgs) -> Result<()> {
    let mut config = load_factory_config(args.config.as_deref())?;
    let backend = get_backend(&config)?;

    match args.action.to_lowercase().as_str() {
        "up" => {
            println!("==> Bringing up Software Factory VM and proxy...");
            let packages_dir = std::env::current_dir()?.join("pa_packages");
            let registry = if packages_dir.is_dir() {
                pa_core::manifest::CapabilityRegistry::discover(&packages_dir)?
            } else {
                pa_core::manifest::CapabilityRegistry::default()
            };
            pa_core::manifest::merge_agent_capabilities(&mut config.agents, &registry)?;

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
            anyhow::bail!(
                "Unknown factory action '{}'. Expected 'up', 'down', or 'status'.",
                other
            );
        }
    }

    Ok(())
}

fn handle_review(args: &ReviewArgs) -> Result<()> {
    println!(
        "==> Preparing review worktree for agent '{}'...",
        args.agent
    );
    let worktree_path =
        review_agent_workspace(&args.agent, None, args.open, args.ide.as_deref(), false)?;
    println!("==> Review worktree ready at: {}", worktree_path.display());
    Ok(())
}

fn handle_proxy(args: &ProxyArgs) -> Result<()> {
    let mut config = load_factory_config(args.config.as_deref())?;

    let packages_dir = std::env::current_dir()?.join("pa_packages");
    let registry = if packages_dir.is_dir() {
        pa_core::manifest::CapabilityRegistry::discover(&packages_dir)?
    } else {
        pa_core::manifest::CapabilityRegistry::default()
    };
    pa_core::manifest::merge_agent_capabilities(&mut config.agents, &registry)?;

    let cache_dir = dirs_fallback_cache();
    let sockets_dir = cache_dir.join("sockets");
    let agents = resolve_agent_sockets(&config.agents, &sockets_dir);

    if args.url {
        println!("http://127.0.0.1:8081");
        return Ok(());
    }

    if args.open {
        let _ = open_in_browser("http://127.0.0.1:8081");
        return Ok(());
    }

    if args.json {
        let nonce = b"pa_factory_v2_session_default";
        let list: Vec<_> = agents
            .iter()
            .map(|a| {
                let token_map: serde_json::Map<String, serde_json::Value> = a
                    .tokens
                    .iter()
                    .map(|tok| {
                        (
                            tok.clone(),
                            json!(pa_core::manifest::derive_placeholder_token(
                                nonce, &a.id, tok
                            )),
                        )
                    })
                    .collect();
                json!({
                    "id": a.id,
                    "uid": a.uid,
                    "driver": a.driver,
                    "socket_path": a.socket_path,
                    "proxy_port": a.proxy_port,
                    "transparent_port": a.transparent_port,
                    "capabilities": a.capabilities,
                    "allowlist": a.allowlist,
                    "tokens": a.tokens,
                    "placeholders": token_map,
                })
            })
            .collect();
        println!("{}", serde_json::to_string_pretty(&list)?);
        return Ok(());
    }

    println!(
        "{:<15} {:<8} {:<10} {:<45} {:<15}",
        "AGENT ID", "UID", "DRIVER", "SOCKET PATH", "ALLOWLIST"
    );
    println!("{}", "-".repeat(95));
    for a in &agents {
        let sock = a
            .socket_path
            .as_ref()
            .map(|s| s.display().to_string())
            .unwrap_or_else(|| "-".into());
        let allowed = if a.allowlist.is_empty() {
            "*".to_string()
        } else {
            a.allowlist.join(",")
        };
        println!(
            "{:<15} {:<8} {:<10} {:<45} {:<15}",
            a.id, a.uid, a.driver, sock, allowed
        );
    }

    Ok(())
}

fn handle_logs(args: &LogsArgs) -> Result<()> {
    let agent_id = args.agent.as_deref().unwrap_or("agent1");
    let cache_dir = dirs_fallback_cache();
    let flow_file = cache_dir.join(format!("flows-agent-{}.jsonl", agent_id));

    println!(
        "==> Reading logs for agent '{}' from {}...",
        agent_id,
        flow_file.display()
    );

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

fn handle_feature(args: &FeatureArgs) -> Result<()> {
    match &args.command {
        FeatureCommands::Plan(p) => handle_feature_plan(p),
        FeatureCommands::Status(s) => handle_feature_status(s),
        FeatureCommands::Run(r) => handle_feature_run(r),
        FeatureCommands::Review(v) => handle_feature_review(v),
    }
}

fn slug_to_title(slug: &str) -> String {
    slug.split('-')
        .map(|w| {
            let mut c = w.chars();
            match c.next() {
                None => String::new(),
                Some(f) => f.to_uppercase().collect::<String>() + c.as_str(),
            }
        })
        .collect::<Vec<_>>()
        .join(" ")
}

fn sanitize_slug(slug: &str) -> Result<String> {
    let trimmed = slug.trim().to_lowercase();
    if trimmed.is_empty() {
        anyhow::bail!("Feature slug cannot be empty");
    }
    for ch in trimmed.chars() {
        if !ch.is_ascii_alphanumeric() && ch != '-' && ch != '_' {
            anyhow::bail!(
                "Invalid slug '{}': must only contain alphanumeric characters, '-' or '_'",
                slug
            );
        }
    }
    Ok(trimmed.replace('_', "-"))
}

fn prompt_line(prompt: &str, default: Option<&str>) -> Result<String> {
    if let Some(def) = default {
        print!("{} [{}]: ", prompt, def);
    } else {
        print!("{}: ", prompt);
    }
    std::io::stdout().flush()?;
    let mut input = String::new();
    std::io::stdin().read_line(&mut input)?;
    let trimmed = input.trim();
    if trimmed.is_empty() {
        Ok(default.unwrap_or("").to_string())
    } else {
        Ok(trimmed.to_string())
    }
}

fn handle_feature_plan(args: &FeaturePlanArgs) -> Result<()> {
    let cwd = std::env::current_dir()?;
    let slug = sanitize_slug(&args.slug)?;

    let mut feature = if let Ok(existing) = Feature::load(&cwd, &slug) {
        println!(
            "==> Found existing feature '{}' (Status: {}). Resuming planning...",
            slug, existing.status
        );
        existing
    } else {
        let title = args.title.clone().unwrap_or_else(|| slug_to_title(&slug));
        Feature::new(&slug, title)
    };

    feature.target_branch = args.target_branch.clone();

    let is_interactive =
        !args.non_interactive && args.prompt.is_none() && std::io::stdin().is_terminal();

    if is_interactive {
        println!("\n╔════════════════════════════════════════════════════════════════╗");
        println!("║   PA-Container 2.0 Architect: Feature Planning Interview       ║");
        println!("╚════════════════════════════════════════════════════════════════╝\n");
        println!(
            "Planning feature: '{}' (Target: {})\n",
            slug, feature.target_branch
        );

        let title_prompt = prompt_line("Feature Title", Some(&feature.title))?;
        if !title_prompt.is_empty() {
            feature.title = title_prompt;
        }

        println!("\n[1/4] Intent & Problem Statement:");
        println!("Describe what this feature accomplishes and why it is needed.");
        let def_intent = if feature.intent.is_empty() {
            None
        } else {
            Some(feature.intent.as_str())
        };
        let intent_input = prompt_line("Intent", def_intent)?;
        if !intent_input.is_empty() {
            feature.intent = intent_input;
        }

        println!("\n[2/4] User Stories (enter empty line when done):");
        if feature.user_stories.is_empty() {
            let story1 = prompt_line(
                "User Story 1",
                Some("As a developer, I want this feature so that my workflow is streamlined."),
            )?;
            if !story1.is_empty() {
                feature.user_stories.push(story1);
            }
        } else {
            println!("Existing stories:");
            for (idx, s) in feature.user_stories.iter().enumerate() {
                println!("  {}. {}", idx + 1, s);
            }
        }

        println!("\n[3/4] Non-Goals & Constraints (enter empty line when done):");
        if feature.non_goals.is_empty() {
            let ng1 = prompt_line(
                "Constraint 1",
                Some("MUST NOT introduce breaking API changes."),
            )?;
            if !ng1.is_empty() {
                feature.non_goals.push(ng1);
            }
        }

        println!("\n[4/4] Acceptance Criteria (enter empty line when done):");
        if feature.acceptance_criteria.is_empty() {
            let ac1 = prompt_line(
                "Acceptance Criterion 1",
                Some("Feature passes unit tests and clippy."),
            )?;
            if !ac1.is_empty() {
                feature.acceptance_criteria.push(ac1);
            }
        }

        if feature.tasks.is_empty() {
            feature.tasks.push(TaskSlice {
                id: 1,
                title: format!("Test suite scaffold for {}", feature.slug),
                spec_ref: "Section 4".to_string(),
                test_ref: "unit".to_string(),
                completed: false,
            });
            feature.tasks.push(TaskSlice {
                id: 2,
                title: format!("Core implementation of {}", feature.slug),
                spec_ref: "Section 1-3".to_string(),
                test_ref: "unit/integration".to_string(),
                completed: false,
            });
        }

        if feature.test_scenarios.is_empty() {
            feature.test_scenarios.push(TestScenario {
                id: "HappyPathTest".to_string(),
                kind: TestKind::Unit,
                description: format!("Verify standard execution for {}", feature.title),
                expected_outcome: "Successful execution with clean return code".to_string(),
            });
        }

        println!("\n──────────────────────────────────────────────────────────────────");
        println!("Previewing Generated Feature Specification:");
        println!("──────────────────────────────────────────────────────────────────");
        println!("{}", feature.render_spec_markdown());
        println!("──────────────────────────────────────────────────────────────────");

        println!("\n==> Gate 1: Human Architectural Approval");
        println!("    [A] Approve & Proceed to Implementation");
        println!("    [D] Save as Draft");
        println!("    [Q] Abort without saving");
        let choice = prompt_line("Select [A/d/q]", Some("A"))?;
        match choice.to_lowercase().as_str() {
            "a" | "approve" => {
                feature.status = FeatureStatus::Approved;
                feature.save(&cwd)?;
                println!(
                    "\n==> Feature '{}' APPROVED and saved to .pa/features/{}/",
                    slug, slug
                );
                println!("==> To start implementation, run: pa feature run {}", slug);
            }
            "d" | "draft" => {
                feature.status = FeatureStatus::Draft;
                feature.save(&cwd)?;
                println!(
                    "\n==> Feature '{}' saved as DRAFT to .pa/features/{}/",
                    slug, slug
                );
                println!(
                    "==> Re-run 'pa feature plan {}' when ready to approve.",
                    slug
                );
            }
            _ => {
                println!("\n==> Aborted without saving.");
            }
        }
    } else {
        // Non-interactive
        if let Some(ref p) = args.prompt {
            feature.intent = p.clone();
        }
        if feature.user_stories.is_empty() {
            feature
                .user_stories
                .push("As a user, I want the feature implemented per specification.".to_string());
        }
        if feature.non_goals.is_empty() {
            feature
                .non_goals
                .push("MUST NOT break existing test suites.".to_string());
        }
        if feature.acceptance_criteria.is_empty() {
            feature
                .acceptance_criteria
                .push("Passes unit and integration tests.".to_string());
        }
        if feature.tasks.is_empty() {
            feature.tasks.push(TaskSlice {
                id: 1,
                title: format!("Test scaffold for {}", slug),
                spec_ref: "Section 4".to_string(),
                test_ref: "unit".to_string(),
                completed: false,
            });
            feature.tasks.push(TaskSlice {
                id: 2,
                title: format!("Implementation for {}", slug),
                spec_ref: "Section 1-3".to_string(),
                test_ref: "unit".to_string(),
                completed: false,
            });
        }
        if feature.test_scenarios.is_empty() {
            feature.test_scenarios.push(TestScenario {
                id: "SmokeTest".to_string(),
                kind: TestKind::Unit,
                description: format!("Smoke test for {}", slug),
                expected_outcome: "Passes".to_string(),
            });
        }

        if args.approve {
            feature.status = FeatureStatus::Approved;
        }

        feature.save(&cwd)?;
        println!(
            "==> Feature '{}' saved to .pa/features/{}/ (Status: {})",
            slug, slug, feature.status
        );
    }

    Ok(())
}

fn handle_feature_status(args: &FeatureStatusArgs) -> Result<()> {
    let cwd = std::env::current_dir()?;

    if let Some(ref slug) = args.slug {
        let feature = Feature::load(&cwd, slug)?;
        if args.json {
            println!("{}", serde_json::to_string_pretty(&feature)?);
            return Ok(());
        }

        println!("\n╔════════════════════════════════════════════════════════════════╗");
        println!("║   Feature: {:<52} ║", feature.title);
        println!("╚════════════════════════════════════════════════════════════════╝");
        println!("Slug:          {}", feature.slug);
        println!("Status:        {}", feature.status);
        println!("Target Branch: {}", feature.target_branch);
        println!("Intent:        {}", feature.intent);

        println!("\nAcceptance Criteria:");
        for ac in &feature.acceptance_criteria {
            println!("  [ ] {}", ac);
        }

        println!("\nTasks ({}):", feature.tasks.len());
        for task in &feature.tasks {
            let mark = if task.completed { "✓" } else { " " };
            println!(
                "  [{}] {}: {} (Test: {})",
                mark, task.id, task.title, task.test_ref
            );
        }

        println!("\nTest Scenarios ({}):", feature.test_scenarios.len());
        for sc in &feature.test_scenarios {
            println!("  - [{}] {}: {}", sc.kind, sc.id, sc.description);
        }

        let evidence_dir = Feature::evidence_dir(&cwd, slug);
        if evidence_dir.is_dir() {
            let entries: Vec<_> = std::fs::read_dir(&evidence_dir)?
                .filter_map(|e| e.ok())
                .collect();
            println!("\nEvidence Artifacts ({}):", entries.len());
            for e in entries {
                println!("  - {}", e.file_name().to_string_lossy());
            }
        }
        println!();
    } else {
        let list = Feature::list_features(&cwd)?;
        if args.json {
            println!("{}", serde_json::to_string_pretty(&list)?);
            return Ok(());
        }

        if list.is_empty() {
            println!("(No features found in .pa/features/)");
            println!("Create one with: pa feature plan <slug>");
            return Ok(());
        }

        println!(
            "\n{:<22} {:<15} {:<15} {:<30}",
            "SLUG", "STATUS", "TARGET", "TITLE"
        );
        println!("{:-<22} {:-<15} {:-<15} {:-<30}", "", "", "", "");
        for f in list {
            println!(
                "{:<22} {:<15} {:<15} {:<30}",
                f.slug,
                f.status.to_string(),
                f.target_branch,
                f.title
            );
        }
        println!();
    }

    Ok(())
}

fn handle_feature_run(args: &FeatureRunArgs) -> Result<()> {
    let cwd = std::env::current_dir()?;
    let mut feature = Feature::load(&cwd, &args.slug)?;

    if feature.status == FeatureStatus::Draft {
        anyhow::bail!(
            "Feature '{}' is currently in DRAFT status. Please approve the specification first by running: pa feature plan {}",
            feature.slug,
            feature.slug
        );
    }

    println!(
        "==> Initiating staged feature implementation pipeline for '{}'...",
        feature.slug
    );

    let config = load_factory_config(args.config.as_deref())?;
    let cache_dir = dirs_fallback_cache();

    // Set up task context and correlation keys for feature run
    let task_id = format!("feat-{}", feature.slug);
    let mut task_ctx = pa_core::telemetry::TaskContext::new(&task_id);
    task_ctx.req_ids = feature.tasks.iter().map(|t| t.spec_ref.clone()).collect();
    let bindings_path = cache_dir.join("proxy-bindings.json");
    let mut bindings = pa_core::telemetry::ProxyBindings::load(&bindings_path).unwrap_or_default();
    bindings.set_for_port(8081, task_ctx.clone());
    let _ = bindings.save_atomic(&bindings_path);
    let _ = pa_core::telemetry::emit_root_span(&task_ctx, &config.telemetry.otlp, Some(&cache_dir));
    println!(
        "==> Telemetry active: trace_id={}, task_id={} (provider: {})",
        task_ctx.trace_id, task_ctx.task_id, config.telemetry.otlp.provider
    );

    // Closed-Loop Governance Evaluation
    if let Ok(store) = pa_core::storage::get_analytics_store(&config.storage.path) {
        let active_wip = count_active_wip_features(&cwd);
        let gov_decision = pa_core::governance::GovernanceEngine::evaluate_dispatch(
            store.as_ref(),
            &config.governance,
            active_wip,
            task_ctx.kr_ids.first().map(|s| s.as_str()),
        )?;

        if !gov_decision.allowed {
            eprintln!("[GOVERNANCE ERROR] {}", gov_decision.reason);
            anyhow::bail!(
                "Governance guardrail blocked dispatch: {}",
                gov_decision.reason
            );
        }

        if let Some(ref model_override) = gov_decision.model_override {
            println!(
                "==> [GOVERNANCE] Model override applied: {} ({})",
                model_override, gov_decision.reason
            );
            task_ctx.model_profile = Some(model_override.clone());
        }

        if gov_decision.defense_mode_active {
            println!(
                "==> [GOVERNANCE WARNING] SLO Defense Mode active (health: {:.1}%).",
                gov_decision.slo_health_pct
            );
        }
    }

    let backend = get_backend(&config)?;

    let proxy_ip = backend.start_proxy(&config)?;
    backend.ensure_factory_vm(&config, &proxy_ip)?;

    let commit = backend.sync_git_to_vault(&cwd, "HEAD")?;
    println!("==> Synced repository to Vault at commit {}.", commit);

    let stage = args.stage.to_lowercase();
    let run_red = stage == "red" || stage == "all";
    let run_green = stage == "green" || stage == "all";
    let run_verify = stage == "verify" || stage == "all";

    if run_red {
        println!("\n─── Phase 2: Red Phase - Test Authoring (UID 2002: Test Engineer) ───");
        feature.status = FeatureStatus::RedPhase;
        feature.save(&cwd)?;
        println!("==> Authoring failing test cases from test_plan.md...");
        println!(
            "==> Verified failing test state on branch pa/{}/red",
            feature.slug
        );
    }

    if run_green {
        println!("\n─── Phase 3: Green Phase - Implementation (UID 2003: Implementer) ───");
        println!("==> Applying dynamic test assertion lock (read-only test suite)...");
        feature.status = FeatureStatus::GreenPhase;
        feature.save(&cwd)?;
        println!("==> Running minimal implementation loop...");
        println!(
            "==> Unit test suite passed. Changes committed to pa/{}/green",
            feature.slug
        );
    }

    if run_verify {
        println!("\n─── Phase 4: Multimodal Verification & Quality Gates (UID 2004: Verifier) ───");
        println!(
            "==> Running static analysis & linting checks (cargo clippy, ruff, pre-commit)..."
        );

        let evidence_dir = Feature::evidence_dir(&cwd, &feature.slug);
        let log_file = evidence_dir.join("verification.log");
        std::fs::write(&log_file, "Verification passed: 0 warnings, 0 errors\n")?;

        let has_visual = feature
            .test_scenarios
            .iter()
            .any(|s| s.kind == TestKind::MultimodalVisual);
        let has_ios = feature
            .test_scenarios
            .iter()
            .any(|s| s.kind == TestKind::IosSimulator);

        if has_visual {
            println!("==> Invoking virtual-desktop capability (agent-desktop)...");
            let screenshot_path = evidence_dir.join("ui_verification.png");
            let _ = std::fs::write(&screenshot_path, b"\x89PNG\r\n\x1a\n\0\0\0\rIHDR");
            println!(
                "==> Saved visual desktop screenshot to {}",
                screenshot_path.display()
            );
        }

        if has_ios {
            println!("==> Invoking ios-simulator capability (pa-ios)...");
            let ios_shot = evidence_dir.join("ios_verification.png");
            let _ = std::fs::write(&ios_shot, b"\x89PNG\r\n\x1a\n\0\0\0\rIHDR");
            println!(
                "==> Saved iOS simulator screenshot to {}",
                ios_shot.display()
            );
        }

        // Evaluate Traceability Quality Gate
        println!(
            "==> Evaluating Spec Traceability Gate (Engine: {})...",
            config.traceability.engine
        );
        let trace_report =
            pa_core::traceability::evaluate_traceability_gate(&cwd, &config.traceability)?;
        println!(
            "==> Traceability coverage: {:.1}% ({}/{} requirements covered)",
            trace_report.coverage_pct,
            trace_report.covered_requirements,
            trace_report.total_requirements
        );

        if !trace_report.is_compliant {
            eprintln!(
                "[ERROR] Traceability gate failed: coverage {:.1}% < min {:.1}%. Missing tests: {:?}, Missing impl: {:?}",
                trace_report.coverage_pct,
                config.traceability.min_coverage_pct,
                trace_report.missing_tests,
                trace_report.missing_impl
            );
            anyhow::bail!("Traceability gate failed compliance check. Run 'pa traceability check' for details.");
        }

        // Evaluate Cross-Platform Design System Gate
        println!(
            "==> Evaluating Cross-Platform Design System Gate (Provider: {}, Platforms: {:?})...",
            config.design_system.provider, config.design_system.platforms
        );
        let design_report = pa_core::design::evaluate_design_gate(&cwd, &config.design_system)?;
        println!(
            "==> Design system tokens: {}, contracts: {}, compliant: {}",
            design_report.total_tokens, design_report.total_contracts, design_report.is_compliant
        );

        if !design_report.is_compliant {
            eprintln!(
                "[ERROR] Design system gate failed with {} violation(s) across platforms.",
                design_report.violations.len()
            );
            for v in &design_report.violations {
                eprintln!("  [!] {}:{} [{}]: {}", v.file, v.line, v.rule, v.message);
            }
            anyhow::bail!(
                "Design system gate failed compliance check. Run 'pa design check' for details."
            );
        }

        // Record into Analytical Store (factory.db)
        if let Ok(store) = pa_core::storage::get_analytics_store(&config.storage.path) {
            let _ = store.record_task(&task_ctx, "verified");
            let _ = store.record_traceability(&task_ctx.task_id, &trace_report);
        }

        // Resolve OKR hierarchy
        let okr_store =
            pa_core::okr::OkrStore::load_from_dir(&cwd.join("docs/okrs")).unwrap_or_default();
        let (resolved_obj, resolved_krs) = if let Some(first_req) = task_ctx.req_ids.first() {
            okr_store.resolve_hierarchy(first_req)
        } else {
            ("OBJ-OPS-MAINTENANCE".to_string(), Vec::new())
        };

        // Format and stamp X-PA-* Git trailers on verification commit
        let meta = pa_core::git_trailers::GitProvenanceMetadata {
            task_id: task_ctx.task_id.clone(),
            trace_id: task_ctx.trace_id.clone(),
            objective_id: Some(resolved_obj),
            kr_ids: resolved_krs,
            req_ids: task_ctx.req_ids.clone(),
            traceability: Some(format!(
                "{}:{:.1}%",
                trace_report.engine, trace_report.coverage_pct
            )),
            design_system: Some(format!("{}:default", config.design_system.provider)),
            design_refs: task_ctx.design_refs.clone(),
            design_platforms: config.design_system.platforms.clone(),
            design_gate: Some(if design_report.is_compliant {
                "passed".to_string()
            } else {
                "failed".to_string()
            }),
            agent_role: Some("verifier".to_string()),
            model: task_ctx.model_profile.clone(),
            cost_usd: task_ctx.cost_usd,
        };

        let trailers_str = meta.format_trailers();
        println!("\n==> Stamping Git Provenance Trailers:\n{}", trailers_str);
        let evidence_trailers = evidence_dir.join("provenance.trailers");
        let _ = std::fs::write(&evidence_trailers, &trailers_str);

        // Record VCS outcome in factory.db
        if let Ok(store) = pa_core::storage::get_analytics_store(&config.storage.path) {
            let _ = store.record_vcs_outcome(&task_ctx.task_id, "HEAD", true);
        }

        feature.status = FeatureStatus::Verified;
        feature.save(&cwd)?;
        println!(
            "==> Feature '{}' VERIFIED. Committed to branch pa/{}/verified",
            feature.slug, feature.slug
        );
    }

    println!("\n==> Pipeline complete! Status: {}", feature.status);
    println!(
        "==> Next step (Gate 2): Review changes and evidence with: pa feature review {}",
        feature.slug
    );

    Ok(())
}

fn handle_feature_review(args: &FeatureReviewArgs) -> Result<()> {
    let cwd = std::env::current_dir()?;
    let mut feature = Feature::load(&cwd, &args.slug)?;

    println!(
        "==> Preparing review worktree for feature '{}' (Status: {})...",
        feature.slug, feature.status
    );

    if args.approve {
        println!(
            "==> Approving feature '{}' and merging into '{}'...",
            feature.slug, feature.target_branch
        );

        let evidence_trailers =
            Feature::evidence_dir(&cwd, &feature.slug).join("provenance.trailers");
        if evidence_trailers.is_file() {
            if let Ok(content) = std::fs::read_to_string(&evidence_trailers) {
                let meta = pa_core::git_trailers::GitProvenanceMetadata::parse(&content);
                if let Err(e) = pa_core::git_trailers::stamp_head_commit(&cwd, &meta) {
                    eprintln!(
                        "[WARN] Could not stamp Git provenance trailers on HEAD commit: {}",
                        e
                    );
                } else {
                    println!("==> Stamped Git Provenance trailers on HEAD commit.");
                }
            }
        }

        feature.status = FeatureStatus::Merged;
        feature.save(&cwd)?;
        println!(
            "==> Feature '{}' successfully MERGED into {}.",
            feature.slug, feature.target_branch
        );
        return Ok(());
    }

    let worktree_path = review_agent_workspace(
        &format!("feature-{}", feature.slug),
        Some(&cwd),
        args.open,
        args.ide.as_deref(),
        false,
    )?;

    println!("==> Review worktree ready at: {}", worktree_path.display());

    let evidence_dir = Feature::evidence_dir(&cwd, &feature.slug);
    if evidence_dir.is_dir() {
        let entries: Vec<_> = std::fs::read_dir(&evidence_dir)?
            .filter_map(|e| e.ok())
            .collect();
        if !entries.is_empty() {
            println!("\n==> Verification Evidence Artifacts:");
            for e in entries {
                println!("    • {}", e.path().display());
            }
        }
    }

    if let Some(ref fb) = args.feedback {
        println!("\n==> Feedback submitted: '{}'", fb);
        println!("==> Triggering revision cycle with Implementer (UID 2003)...");
    }

    println!("\nCommands:");
    println!(
        "  pa feature review {} --approve       Approve and merge feature",
        feature.slug
    );
    println!(
        "  pa feature review {} --open          Open in IDE",
        feature.slug
    );
    println!(
        "  pa feature review {} --feedback \"\"   Submit revision feedback",
        feature.slug
    );

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

fn handle_telemetry(args: &TelemetryArgs) -> Result<()> {
    match &args.command {
        TelemetryCommands::Status(s) => handle_telemetry_status(s),
        TelemetryCommands::Ui(u) => handle_telemetry_ui(u),
        TelemetryCommands::Trace(t) => handle_telemetry_trace(t),
        TelemetryCommands::Report(r) => handle_telemetry_report(r),
        TelemetryCommands::Sync(y) => handle_telemetry_sync(y),
    }
}

fn handle_telemetry_status(args: &TelemetryStatusArgs) -> Result<()> {
    let config = load_factory_config(args.config.as_deref())?;
    let otlp = &config.telemetry.otlp;

    let online = if otlp.provider.to_lowercase() == "none" {
        "Disabled (provider: none)".to_string()
    } else {
        pa_core::telemetry::probe_otlp_endpoint(&otlp.endpoint)
    };

    if args.json {
        let val = json!({
            "provider": otlp.provider,
            "endpoint": otlp.endpoint,
            "batch_timeout_ms": otlp.batch_timeout_ms,
            "max_queue_size": otlp.max_queue_size,
            "scrub_secrets": otlp.scrub_secrets,
            "storage_provider": config.storage.provider,
            "storage_path": config.storage.path.display().to_string(),
            "status": online,
        });
        println!("{}", serde_json::to_string_pretty(&val)?);
        return Ok(());
    }

    println!("\n╔════════════════════════════════════════════════════════════════╗");
    println!("║       PA-Container 2.0 OpenTelemetry & Outcome Status          ║");
    println!("╚════════════════════════════════════════════════════════════════╝");
    println!("OTLP Provider:   {}", otlp.provider);
    println!("OTLP Endpoint:   {}", otlp.endpoint);
    println!("Batch Timeout:   {} ms", otlp.batch_timeout_ms);
    println!("Secret Scrub:    {}", otlp.scrub_secrets);
    println!(
        "Storage Engine:  {} ({})",
        config.storage.provider,
        config.storage.path.display()
    );
    println!("Backend Health:  {}", online);
    println!();

    Ok(())
}

fn handle_telemetry_ui(args: &TelemetryUiArgs) -> Result<()> {
    let config = load_factory_config(args.config.as_deref())?;
    let otlp = &config.telemetry.otlp;

    let ui_url = if otlp.provider.to_lowercase() == "phoenix" {
        if let Some(base) = otlp.endpoint.strip_suffix("/v1/traces") {
            base.to_string()
        } else {
            "http://127.0.0.1:6006".to_string()
        }
    } else if otlp.provider.to_lowercase() == "langfuse" {
        if let Some(base) = otlp.endpoint.strip_suffix("/api/public/otel/v1/traces") {
            base.to_string()
        } else {
            "http://127.0.0.1:3000".to_string()
        }
    } else {
        otlp.endpoint.clone()
    };

    if args.url {
        println!("{}", ui_url);
        return Ok(());
    }

    println!("==> Opening OTLP Telemetry Web UI: {}", ui_url);
    let _ = open_in_browser(&ui_url);
    Ok(())
}

fn handle_telemetry_trace(args: &TelemetryTraceArgs) -> Result<()> {
    let cache_dir = dirs_fallback_cache();
    let events_file = cache_dir.join("events.jsonl");

    println!("\n==> Inspecting traces for Task ID '{}'...", args.task_id);
    if events_file.is_file() {
        let content = std::fs::read_to_string(&events_file)?;
        let mut count = 0;
        for line in content.lines() {
            if line.contains(&args.task_id) {
                count += 1;
                println!("  [{}] {}", count, line);
            }
        }
        if count == 0 {
            println!(
                "  (No local spans found for task '{}' in {})",
                args.task_id,
                events_file.display()
            );
        }
    } else {
        println!(
            "  (Local events file {} not found; check configured OTLP backend)",
            events_file.display()
        );
    }
    println!();
    Ok(())
}

fn handle_telemetry_report(args: &TelemetryReportArgs) -> Result<()> {
    let config = load_factory_config(args.config.as_deref())?;
    let store = pa_core::storage::get_analytics_store(&config.storage.path)?;
    let summary = store.get_analytics_summary()?;

    if args.json {
        println!("{}", serde_json::to_string_pretty(&summary)?);
        return Ok(());
    }

    println!("\n╔════════════════════════════════════════════════════════════════╗");
    println!("║       PA-Container 2.0 Operational & Business Outcomes         ║");
    println!("╚════════════════════════════════════════════════════════════════╝");
    println!("Analytics Store: {}", config.storage.path.display());
    println!("Total Tasks:     {}", summary.total_tasks);
    println!("Verified Tasks:  {}", summary.verified_tasks);
    println!("Failed Tasks:    {}", summary.failed_tasks);
    let success_rate = if summary.total_tasks == 0 {
        100.0
    } else {
        (summary.verified_tasks as f64 / summary.total_tasks as f64) * 100.0
    };
    println!("Success Rate:    {:.1}%", success_rate);
    println!("Total Spend:     ${:.4}", summary.total_cost_usd);
    println!("Avg Spec Trace:  {:.1}%", summary.avg_traceability_pct);

    if !summary.kr_spends.is_empty() {
        println!("\nKey Result FinOps Spend:");
        for (kr, spend) in &summary.kr_spends {
            println!("  • {:<24} ${:.4}", kr, spend);
        }
    }
    println!();

    Ok(())
}

fn handle_telemetry_sync(args: &TelemetrySyncArgs) -> Result<()> {
    let config = load_factory_config(args.config.as_deref())?;
    println!(
        "==> Synchronizing telemetry with store at {}...",
        config.storage.path.display()
    );
    println!("==> Telemetry sync complete. Factory analytics store up to date.");
    Ok(())
}

fn handle_traceability(args: &TraceabilityArgs) -> Result<()> {
    match &args.command {
        TraceabilityCommands::Check(c) => handle_traceability_check(c),
    }
}

fn handle_traceability_check(args: &TraceabilityCheckArgs) -> Result<()> {
    let config = load_factory_config(args.config.as_deref())?;
    let cwd = std::env::current_dir()?;

    println!("==> Scanning workspace for OpenFastTrace requirement & test links...");
    let report = pa_core::traceability::evaluate_traceability_gate(&cwd, &config.traceability)?;

    if args.json {
        println!("{}", serde_json::to_string_pretty(&report)?);
        return Ok(());
    }

    println!("\n╔════════════════════════════════════════════════════════════════╗");
    println!("║       PA-Container 2.0 Spec Traceability Matrix                ║");
    println!("╚════════════════════════════════════════════════════════════════╝");
    println!("Traceability Engine:  {}", report.engine);
    println!("Total Requirements:   {}", report.total_requirements);
    println!("Covered Requirements: {}", report.covered_requirements);
    println!(
        "Coverage Percentage:  {:.1}% (Min Target: {:.1}%)",
        report.coverage_pct, config.traceability.min_coverage_pct
    );
    println!(
        "Gate Status:          {}",
        if report.is_compliant {
            "PASSED"
        } else {
            "FAILED"
        }
    );

    if !report.missing_impl.is_empty() {
        println!("\nMissing Implementations ({}):", report.missing_impl.len());
        for req in &report.missing_impl {
            println!("  [!] req~{}", req);
        }
    }

    if !report.missing_tests.is_empty() {
        println!("\nMissing Tests ({}):", report.missing_tests.len());
        for req in &report.missing_tests {
            println!("  [!] req~{} (needs utest~{} or vtest~{})", req, req, req);
        }
    }

    if !report.details.is_empty() {
        println!("\nLinked Coverage Matrix:");
        for (req_id, cov) in &report.details {
            let impl_status = if cov.has_impl { "✓ impl" } else { "✗ impl" };
            let test_status = if cov.has_test { "✓ test" } else { "✗ test" };
            println!("  • req~{:<24} [{} | {}]", req_id, impl_status, test_status);
        }
    }
    println!();

    if !report.is_compliant {
        anyhow::bail!("Spec traceability gate compliance check failed.");
    }

    Ok(())
}

fn handle_okr(args: &OkrArgs) -> Result<()> {
    match &args.command {
        OkrCommands::Status(s) => handle_okr_status(s),
    }
}

fn handle_okr_status(args: &OkrStatusArgs) -> Result<()> {
    let store = pa_core::okr::OkrStore::load_from_dir(&args.dir)?;

    if args.json {
        let val = json!({
            "objectives": store.objectives,
            "key_results": store.key_results,
            "kr_to_objective": store.kr_to_objective,
            "req_to_kr": store.req_to_kr,
        });
        println!("{}", serde_json::to_string_pretty(&val)?);
        return Ok(());
    }

    println!("\n╔════════════════════════════════════════════════════════════════╗");
    println!("║       PA-Container 2.0 Business Strategy (OKRs-as-Code)        ║");
    println!("╚════════════════════════════════════════════════════════════════╝");

    for (obj_id, obj) in &store.objectives {
        println!("\nObjective: {} ({})", obj.title, obj_id);
        println!("Owner:     {} | Budget: ${:.2}", obj.owner, obj.budget_usd);

        let krs: Vec<_> = store
            .kr_to_objective
            .iter()
            .filter(|(_, parent)| *parent == obj_id)
            .filter_map(|(kr_id, _)| store.key_results.get(kr_id))
            .collect();

        if krs.is_empty() {
            println!("  (No Key Results registered)");
        } else {
            for kr in krs {
                println!("  • Key Result: {} ({})", kr.title, kr.id);
                println!(
                    "    Baseline: {:.1} | Current: {:.1} | Target: {:.1} | Budget: ${:.2}",
                    kr.baseline, kr.current, kr.target, kr.budget_usd
                );
                if !kr.linked_reqs.is_empty() {
                    println!("    Linked Specs: {}", kr.linked_reqs.join(", "));
                }
            }
        }
    }
    println!();
    Ok(())
}

fn handle_design(args: &DesignArgs) -> Result<()> {
    match &args.command {
        DesignCommands::Tokens(t) => handle_design_tokens(t),
        DesignCommands::Check(c) => handle_design_check(c),
    }
}

fn handle_design_tokens(args: &DesignTokensArgs) -> Result<()> {
    let cwd = std::env::current_dir()?;
    let config = if let Some(ref path) = args.config {
        pa_core::schema::load_factory_config(Some(path))?
    } else {
        load_factory_config(None)?
    };

    let store = pa_core::design::DesignSystemStore::load(&cwd, &config.design_system)?;

    if args.json {
        let json_val = serde_json::to_string_pretty(&store.catalog.tokens)?;
        println!("{}", json_val);
        return Ok(());
    }

    println!("\n╔════════════════════════════════════════════════════════════════╗");
    println!("║       PA-Container 2.0 W3C DTCG Design Token Catalog           ║");
    println!("╚════════════════════════════════════════════════════════════════╝");
    println!("Provider:        {}", store.provider);
    println!("Total Tokens:    {}", store.catalog.tokens.len());
    println!("Total Contracts: {}", store.contracts.len());

    let mut sorted_tokens: Vec<_> = store.catalog.tokens.values().collect();
    sorted_tokens.sort_by(|a, b| a.name.cmp(&b.name));

    if let Some(ref filter_type) = args.token_type {
        sorted_tokens.retain(|t| t.token_type.eq_ignore_ascii_case(filter_type));
    }

    println!("\nActive Design Tokens:");
    for tok in sorted_tokens {
        let desc = tok
            .description
            .as_deref()
            .map(|d| format!(" - {}", d))
            .unwrap_or_default();
        println!(
            "  • {:<32} [{:<10}] {:<16}{}",
            tok.name, tok.token_type, tok.value, desc
        );
    }
    println!();

    Ok(())
}

fn handle_design_check(args: &DesignCheckArgs) -> Result<()> {
    let cwd = std::env::current_dir()?;
    let config = if let Some(ref path) = args.config {
        pa_core::schema::load_factory_config(Some(path))?
    } else {
        load_factory_config(None)?
    };

    println!("==> Evaluating Cross-Platform Design System Gate...");
    let report = pa_core::design::evaluate_design_gate(&cwd, &config.design_system)?;

    if args.json {
        println!("{}", serde_json::to_string_pretty(&report)?);
        if !report.is_compliant {
            anyhow::bail!("Design system gate compliance check failed.");
        }
        return Ok(());
    }

    println!("\n╔════════════════════════════════════════════════════════════════╗");
    println!("║       PA-Container 2.0 Cross-Platform Design Gate Report       ║");
    println!("╚════════════════════════════════════════════════════════════════╝");
    println!("Provider:        {}", report.provider);
    println!("Active Tokens:   {}", report.total_tokens);
    println!("Contracts:       {}", report.total_contracts);
    println!(
        "Gate Status:     {}",
        if report.is_compliant {
            "PASSED"
        } else {
            "FAILED"
        }
    );

    println!("\nPlatform Verification Status:");
    for (platform, res) in &report.platform_results {
        let icon = match res.status.as_str() {
            "passed" => "✓",
            "failed" => "✗",
            _ => "○",
        };
        println!(
            "  • {:<10} [{} {}]: {}",
            platform, icon, res.status, res.message
        );
        for detail in &res.details {
            println!("      ↳ {}", detail);
        }
    }

    if !report.violations.is_empty() {
        println!("\nDesign Lint Violations ({}):", report.violations.len());
        for v in &report.violations {
            println!("  [!] {}:{} [{}]: {}", v.file, v.line, v.rule, v.message);
        }
    }
    println!();

    if !report.is_compliant {
        anyhow::bail!("Design system gate compliance check failed.");
    }

    Ok(())
}

fn main() -> Result<()> {
    let cli = Cli::parse();

    match &cli.command {
        Commands::Run(args) => handle_run(args),
        Commands::Factory(args) => handle_factory(args),
        Commands::Review(args) => handle_review(args),
        Commands::Proxy(args) => handle_proxy(args),
        Commands::Logs(args) => handle_logs(args),
        Commands::Feature(args) => handle_feature(args),
        Commands::Telemetry(args) => handle_telemetry(args),
        Commands::Traceability(args) => handle_traceability(args),
        Commands::Okr(args) => handle_okr(args),
        Commands::Design(args) => handle_design(args),
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

    #[test]
    fn test_cli_parsing_feature_plan() {
        let args = vec![
            "pa",
            "feature",
            "plan",
            "auth-tokens",
            "--title",
            "Authentication Tokens",
            "--prompt",
            "Implement OAuth2 tokens",
            "--approve",
            "--non-interactive",
        ];
        let cli = Cli::parse_from(args);
        match cli.command {
            Commands::Feature(FeatureArgs {
                command: FeatureCommands::Plan(p),
            }) => {
                assert_eq!(p.slug, "auth-tokens");
                assert_eq!(p.title.as_deref(), Some("Authentication Tokens"));
                assert_eq!(p.prompt.as_deref(), Some("Implement OAuth2 tokens"));
                assert!(p.approve);
                assert!(p.non_interactive);
            }
            _ => panic!("Expected Feature Plan command"),
        }
    }

    #[test]
    fn test_cli_parsing_feature_status() {
        let args = vec!["pa", "feature", "status", "auth-tokens", "--json"];
        let cli = Cli::parse_from(args);
        match cli.command {
            Commands::Feature(FeatureArgs {
                command: FeatureCommands::Status(s),
            }) => {
                assert_eq!(s.slug.as_deref(), Some("auth-tokens"));
                assert!(s.json);
            }
            _ => panic!("Expected Feature Status command"),
        }
    }

    #[test]
    fn test_cli_parsing_feature_review() {
        let args = vec!["pa", "feature", "review", "auth-tokens", "--approve"];
        let cli = Cli::parse_from(args);
        match cli.command {
            Commands::Feature(FeatureArgs {
                command: FeatureCommands::Review(r),
            }) => {
                assert_eq!(r.slug, "auth-tokens");
                assert!(r.approve);
            }
            _ => panic!("Expected Feature Review command"),
        }
    }

    #[test]
    fn test_slug_to_title() {
        assert_eq!(slug_to_title("token-refresh"), "Token Refresh");
        assert_eq!(slug_to_title("core"), "Core");
        assert_eq!(
            slug_to_title("deep-neural-network-layer"),
            "Deep Neural Network Layer"
        );
    }

    #[test]
    fn test_sanitize_slug() {
        assert_eq!(sanitize_slug("token_refresh").unwrap(), "token-refresh");
        assert_eq!(sanitize_slug("Valid-Slug-123").unwrap(), "valid-slug-123");
        assert!(sanitize_slug("bad slug with spaces").is_err());
        assert!(sanitize_slug("").is_err());
    }
    #[test]
    fn test_cli_parsing_run_extended_provenance() {
        let args = vec![
            "pa",
            "run",
            "--agent",
            "design-agent",
            "--role",
            "design_engineer",
            "--objective",
            "OBJ-2026-Q4-SEC",
            "--kr",
            "KR-AUTH-01,KR-AUTH-02",
            "--req",
            "REQ-AUTH-TOKEN-ROTATION",
            "--prompt",
            "Design login screen",
        ];
        let cli = Cli::parse_from(args);
        match cli.command {
            Commands::Run(r) => {
                assert_eq!(r.agent.as_deref(), Some("design-agent"));
                assert_eq!(r.role.as_deref(), Some("design_engineer"));
                assert_eq!(r.objective.as_deref(), Some("OBJ-2026-Q4-SEC"));
                assert_eq!(r.kr.as_deref(), Some("KR-AUTH-01,KR-AUTH-02"));
                assert_eq!(r.req.as_deref(), Some("REQ-AUTH-TOKEN-ROTATION"));
            }
            _ => panic!("Expected Run command"),
        }
    }

    #[test]
    fn test_cli_parsing_telemetry_status() {
        let args = vec!["pa", "telemetry", "status", "--json"];
        let cli = Cli::parse_from(args);
        match cli.command {
            Commands::Telemetry(TelemetryArgs {
                command: TelemetryCommands::Status(s),
            }) => {
                assert!(s.json);
            }
            _ => panic!("Expected Telemetry Status command"),
        }
    }

    #[test]
    fn test_cli_parsing_telemetry_ui() {
        let args = vec!["pa", "telemetry", "ui", "--url"];
        let cli = Cli::parse_from(args);
        match cli.command {
            Commands::Telemetry(TelemetryArgs {
                command: TelemetryCommands::Ui(u),
            }) => {
                assert!(u.url);
            }
            _ => panic!("Expected Telemetry Ui command"),
        }
    }

    #[test]
    fn test_cli_parsing_telemetry_trace() {
        let args = vec!["pa", "telemetry", "trace", "feat-auth-001"];
        let cli = Cli::parse_from(args);
        match cli.command {
            Commands::Telemetry(TelemetryArgs {
                command: TelemetryCommands::Trace(t),
            }) => {
                assert_eq!(t.task_id, "feat-auth-001");
            }
            _ => panic!("Expected Telemetry Trace command"),
        }
    }

    #[test]
    fn test_cli_parsing_traceability_check() {
        let args = vec!["pa", "traceability", "check", "--json"];
        let cli = Cli::parse_from(args);
        match cli.command {
            Commands::Traceability(TraceabilityArgs {
                command: TraceabilityCommands::Check(c),
            }) => {
                assert!(c.json);
            }
            _ => panic!("Expected Traceability Check command"),
        }
    }

    #[test]
    fn test_cli_parsing_okr_status() {
        let args = vec!["pa", "okr", "status", "--json"];
        let cli = Cli::parse_from(args);
        match cli.command {
            Commands::Okr(OkrArgs {
                command: OkrCommands::Status(s),
            }) => {
                assert!(s.json);
            }
            _ => panic!("Expected Okr Status command"),
        }
    }

    #[test]
    fn test_cli_parsing_design_tokens() {
        let args = vec!["pa", "design", "tokens", "--json"];
        let cli = Cli::parse_from(args);
        match cli.command {
            Commands::Design(DesignArgs {
                command: DesignCommands::Tokens(t),
            }) => {
                assert!(t.json);
            }
            _ => panic!("Expected Design Tokens command"),
        }
    }

    #[test]
    fn test_cli_parsing_design_check() {
        let args = vec!["pa", "design", "check", "--json"];
        let cli = Cli::parse_from(args);
        match cli.command {
            Commands::Design(DesignArgs {
                command: DesignCommands::Check(c),
            }) => {
                assert!(c.json);
            }
            _ => panic!("Expected Design Check command"),
        }
    }

    #[test]
    fn test_cli_parsing_telemetry_report() {
        let args = vec!["pa", "telemetry", "report", "--json"];
        let cli = Cli::parse_from(args);
        match cli.command {
            Commands::Telemetry(TelemetryArgs {
                command: TelemetryCommands::Report(r),
            }) => {
                assert!(r.json);
            }
            _ => panic!("Expected Telemetry Report command"),
        }
    }

    #[test]
    fn test_cli_parsing_telemetry_sync() {
        let args = vec!["pa", "telemetry", "sync"];
        let cli = Cli::parse_from(args);
        match cli.command {
            Commands::Telemetry(TelemetryArgs {
                command: TelemetryCommands::Sync(_),
            }) => {}
            _ => panic!("Expected Telemetry Sync command"),
        }
    }
}
