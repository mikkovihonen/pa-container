use anyhow::{anyhow, Context, Result};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::Arc;

use super::{CompiledSkillBundle, SkillDoc};

/// File emitted by a SkillEmitter ready for sandboxed staging
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct EmittedFile {
    pub path: PathBuf,
    pub content: String,
    #[serde(default)]
    pub executable: bool,
}

/// Capabilities and metadata declared by an emitter
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct EmitterCapabilities {
    pub supports_separate_files: bool,
    pub supports_mcp: bool,
    pub mcp_config_path: Option<String>,
    pub skill_layout: String,
}

/// Trait implemented by all agent skill emitters (built-in, declarative, and external)
pub trait SkillEmitter: Send + Sync {
    /// Unique agent identifier (e.g. "pi", "claude", "cursor")
    fn id(&self) -> &str;

    /// Capabilities and layout characteristics
    fn capabilities(&self) -> EmitterCapabilities;

    /// Compile canonical bundle into target files
    fn emit(&self, bundle: &CompiledSkillBundle) -> Result<Vec<EmittedFile>>;
}

/// Security validation: ensure relative path does not escape root via traversal (..) or root prefix
pub fn validate_emitted_path(relative_path: &Path) -> Result<()> {
    if relative_path.is_absolute() {
        return Err(anyhow!(
            "Security violation: emitted path must be relative, got: {}",
            relative_path.display()
        ));
    }
    for component in relative_path.components() {
        match component {
            std::path::Component::ParentDir => {
                return Err(anyhow!(
                    "Security violation: path traversal detected in emitted path: {}",
                    relative_path.display()
                ));
            }
            std::path::Component::Prefix(_) | std::path::Component::RootDir => {
                return Err(anyhow!(
                    "Security violation: invalid root/prefix path component in: {}",
                    relative_path.display()
                ));
            }
            _ => {}
        }
    }
    Ok(())
}

/// Safely write emitted files into base staging directory with containment checks
pub fn write_staged_files(base_dir: &Path, files: &[EmittedFile]) -> Result<Vec<PathBuf>> {
    fs::create_dir_all(base_dir)
        .with_context(|| format!("Failed to create staging directory: {}", base_dir.display()))?;
    let canonical_base = base_dir
        .canonicalize()
        .with_context(|| format!("Failed to canonicalize base dir: {}", base_dir.display()))?;

    let mut written = Vec::new();
    for file in files {
        validate_emitted_path(&file.path)?;
        let target = canonical_base.join(&file.path);

        if let Some(parent) = target.parent() {
            fs::create_dir_all(parent)?;
            let canonical_parent = parent.canonicalize()?;
            if !canonical_parent.starts_with(&canonical_base) {
                return Err(anyhow!(
                    "Security violation: target parent {} escapes staging base {}",
                    canonical_parent.display(),
                    canonical_base.display()
                ));
            }
        }

        let temp_file = target.with_extension(format!("tmp-{}", std::process::id()));
        fs::write(&temp_file, &file.content)
            .with_context(|| format!("Failed to write temporary file {}", temp_file.display()))?;
        fs::rename(&temp_file, &target)
            .with_context(|| format!("Failed to atomic rename to {}", target.display()))?;

        #[cfg(unix)]
        if file.executable {
            use std::os::unix::fs::PermissionsExt;
            let _ = fs::set_permissions(&target, fs::Permissions::from_mode(0o755));
        }

        written.push(target);
    }
    Ok(written)
}

// -----------------------------------------------------------------------------
// Built-in Emitters (Layer 3)
// -----------------------------------------------------------------------------

fn render_skill_markdown(doc: &SkillDoc) -> String {
    let mut out = String::from("---\n");
    out.push_str(&format!("name: {}\n", doc.name));
    if !doc.description.is_empty() {
        out.push_str(&format!(
            "description: \"{}\"\n",
            doc.description.replace('"', "\\\"")
        ));
    }
    if !doc.triggers.is_empty() {
        out.push_str(&format!(
            "triggers: [{}]\n",
            doc.triggers
                .iter()
                .map(|t| format!("\"{}\"", t))
                .collect::<Vec<_>>()
                .join(", ")
        ));
    }
    if !doc.required_mcp.is_empty() {
        out.push_str(&format!(
            "required_mcp: [{}]\n",
            doc.required_mcp
                .iter()
                .map(|m| format!("\"{}\"", m))
                .collect::<Vec<_>>()
                .join(", ")
        ));
    }
    if !doc.tags.is_empty() {
        out.push_str(&format!(
            "tags: [{}]\n",
            doc.tags
                .iter()
                .map(|t| format!("\"{}\"", t))
                .collect::<Vec<_>>()
                .join(", ")
        ));
    }
    out.push_str("---\n\n");
    out.push_str(&doc.body);
    if !out.ends_with('\n') {
        out.push('\n');
    }
    out
}

/// Pi Coding Agent Emitter (`pi`)
pub struct PiEmitter;

impl SkillEmitter for PiEmitter {
    fn id(&self) -> &str {
        "pi"
    }

    fn capabilities(&self) -> EmitterCapabilities {
        EmitterCapabilities {
            supports_separate_files: true,
            supports_mcp: true,
            mcp_config_path: Some(".pi/mcp.json".to_string()),
            skill_layout: "per_skill_file".to_string(),
        }
    }

    fn emit(&self, bundle: &CompiledSkillBundle) -> Result<Vec<EmittedFile>> {
        let mut files = Vec::new();

        // 1. Emit individual skill files into .pi/skills/<name>/SKILL.md
        for skill in &bundle.skills {
            let rel_path = PathBuf::from(".pi")
                .join("skills")
                .join(&skill.name)
                .join("SKILL.md");
            files.push(EmittedFile {
                path: rel_path,
                content: render_skill_markdown(skill),
                executable: false,
            });
        }

        // 2. Emit MCP servers into .pi/mcp.json
        if !bundle.mcp_servers.is_empty() {
            let mut servers_map = BTreeMap::new();
            for server in &bundle.mcp_servers {
                servers_map.insert(
                    server.id.clone(),
                    serde_json::json!({
                        "command": server.command,
                        "args": server.args,
                        "env": server.env,
                    }),
                );
            }
            let mcp_json = serde_json::json!({
                "mcpServers": servers_map
            });
            files.push(EmittedFile {
                path: PathBuf::from(".pi").join("mcp.json"),
                content: serde_json::to_string_pretty(&mcp_json)?,
                executable: false,
            });
        }

        Ok(files)
    }
}

/// Anthropic Claude Code Emitter (`claude`)
pub struct ClaudeEmitter;

impl SkillEmitter for ClaudeEmitter {
    fn id(&self) -> &str {
        "claude"
    }

    fn capabilities(&self) -> EmitterCapabilities {
        EmitterCapabilities {
            supports_separate_files: true,
            supports_mcp: true,
            mcp_config_path: Some(".claude.json".to_string()),
            skill_layout: "per_skill_file".to_string(),
        }
    }

    fn emit(&self, bundle: &CompiledSkillBundle) -> Result<Vec<EmittedFile>> {
        let mut files = Vec::new();

        // 1. Emit CLAUDE.md with role summary and skill table
        let mut claude_md = format!(
            "# Claude Code Guidelines (Role: {})\n\n",
            bundle.role.role_name
        );
        claude_md.push_str(&format!("Model Tier: `{}`\n", bundle.role.model_tier));
        claude_md.push_str(&format!(
            "Skills Merkle Root: `{}`\n\n",
            bundle.role.skills_merkle_root
        ));

        if !bundle.skills.is_empty() {
            claude_md.push_str("## Active Role Skills\n\n");
            for skill in &bundle.skills {
                claude_md.push_str(&format!("- **`{}`**: {}\n", skill.name, skill.description));
            }
            claude_md.push_str("\n---\n\n");
            for skill in &bundle.skills {
                claude_md.push_str(&format!("### Skill: `{}`\n\n", skill.name));
                claude_md.push_str(&skill.body);
                claude_md.push_str("\n\n---\n\n");
            }
        }
        files.push(EmittedFile {
            path: PathBuf::from("CLAUDE.md"),
            content: claude_md,
            executable: false,
        });

        // 2. Emit separate rules into .claude/rules/<name>.md
        for skill in &bundle.skills {
            let rel_path = PathBuf::from(".claude")
                .join("rules")
                .join(format!("{}.md", skill.name));
            files.push(EmittedFile {
                path: rel_path,
                content: render_skill_markdown(skill),
                executable: false,
            });
        }

        // 3. Emit .claude.json MCP configuration
        if !bundle.mcp_servers.is_empty() {
            let mut servers_map = BTreeMap::new();
            for server in &bundle.mcp_servers {
                servers_map.insert(
                    server.id.clone(),
                    serde_json::json!({
                        "command": server.command,
                        "args": server.args,
                        "env": server.env,
                    }),
                );
            }
            let claude_json = serde_json::json!({
                "mcpServers": servers_map
            });
            files.push(EmittedFile {
                path: PathBuf::from(".claude.json"),
                content: serde_json::to_string_pretty(&claude_json)?,
                executable: false,
            });
        }

        Ok(files)
    }
}

/// OpenCode Assistant Emitter (`opencode`)
pub struct OpenCodeEmitter;

impl SkillEmitter for OpenCodeEmitter {
    fn id(&self) -> &str {
        "opencode"
    }

    fn capabilities(&self) -> EmitterCapabilities {
        EmitterCapabilities {
            supports_separate_files: true,
            supports_mcp: true,
            mcp_config_path: Some(".config/opencode/opencode.json".to_string()),
            skill_layout: "per_skill_file".to_string(),
        }
    }

    fn emit(&self, bundle: &CompiledSkillBundle) -> Result<Vec<EmittedFile>> {
        let mut files = Vec::new();

        // 1. Emit instructions into .opencode/instructions.md
        let mut instructions = format!(
            "# OpenCode Instructions (Role: {})\n\n",
            bundle.role.role_name
        );
        for skill in &bundle.skills {
            instructions.push_str(&format!("## {}\n\n", skill.name));
            instructions.push_str(&skill.body);
            instructions.push_str("\n\n");
        }
        files.push(EmittedFile {
            path: PathBuf::from(".opencode").join("instructions.md"),
            content: instructions,
            executable: false,
        });

        // 2. Emit individual skill documents into .config/opencode/skills/<name>.md
        for skill in &bundle.skills {
            let rel_path = PathBuf::from(".config")
                .join("opencode")
                .join("skills")
                .join(format!("{}.md", skill.name));
            files.push(EmittedFile {
                path: rel_path,
                content: render_skill_markdown(skill),
                executable: false,
            });
        }

        // 3. Emit .config/opencode/opencode.json with MCP definitions
        if !bundle.mcp_servers.is_empty() {
            let mut mcp_map = BTreeMap::new();
            for server in &bundle.mcp_servers {
                let mut cmd = vec![server.command.clone()];
                cmd.extend(server.args.clone());
                mcp_map.insert(
                    server.id.clone(),
                    serde_json::json!({
                        "type": "local",
                        "command": cmd,
                        "enabled": true
                    }),
                );
            }
            let opencode_json = serde_json::json!({
                "mcp": mcp_map
            });
            files.push(EmittedFile {
                path: PathBuf::from(".config")
                    .join("opencode")
                    .join("opencode.json"),
                content: serde_json::to_string_pretty(&opencode_json)?,
                executable: false,
            });
        }

        Ok(files)
    }
}

/// Google Antigravity Emitter (`antigravity` / `agy`)
pub struct AntigravityEmitter;

impl SkillEmitter for AntigravityEmitter {
    fn id(&self) -> &str {
        "antigravity"
    }

    fn capabilities(&self) -> EmitterCapabilities {
        EmitterCapabilities {
            supports_separate_files: true,
            supports_mcp: true,
            mcp_config_path: Some(".gemini/antigravity/mcp_config.json".to_string()),
            skill_layout: "per_skill_file".to_string(),
        }
    }

    fn emit(&self, bundle: &CompiledSkillBundle) -> Result<Vec<EmittedFile>> {
        let mut files = Vec::new();

        // 1. Emit individual skills into .gemini/skills/<name>/SKILL.md
        for skill in &bundle.skills {
            let rel_path = PathBuf::from(".gemini")
                .join("skills")
                .join(&skill.name)
                .join("SKILL.md");
            files.push(EmittedFile {
                path: rel_path,
                content: render_skill_markdown(skill),
                executable: false,
            });
        }

        // 2. Emit .gemini/antigravity/mcp_config.json
        if !bundle.mcp_servers.is_empty() {
            let mut servers_map = BTreeMap::new();
            for server in &bundle.mcp_servers {
                servers_map.insert(
                    server.id.clone(),
                    serde_json::json!({
                        "command": server.command,
                        "args": server.args,
                        "env": server.env,
                    }),
                );
            }
            let mcp_cfg = serde_json::json!({
                "mcpServers": servers_map
            });
            files.push(EmittedFile {
                path: PathBuf::from(".gemini")
                    .join("antigravity")
                    .join("mcp_config.json"),
                content: serde_json::to_string_pretty(&mcp_cfg)?,
                executable: false,
            });
        }

        Ok(files)
    }
}

// -----------------------------------------------------------------------------
// Declarative Emitter (Layer 1)
// -----------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DeclarativeDriverSpec {
    pub id: String,
    #[serde(default)]
    pub description: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DeclarativeSkillsSpec {
    #[serde(default = "default_layout")]
    pub layout: String, // "per_skill_file" | "single_markdown_file"
    #[serde(default)]
    pub path_pattern: Option<String>,
    #[serde(default)]
    pub path: Option<String>,
    #[serde(default = "default_true")]
    pub include_frontmatter: bool,
}

fn default_layout() -> String {
    "per_skill_file".to_string()
}

fn default_true() -> bool {
    true
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DeclarativeMcpSpec {
    pub target_path: String,
    #[serde(default = "default_mcp_format")]
    pub format: String, // "json" | "toml"
    #[serde(default = "default_schema_wrapper")]
    pub schema_wrapper: String, // "mcpServers" | "mcp" | "none"
}

fn default_mcp_format() -> String {
    "json".to_string()
}

fn default_schema_wrapper() -> String {
    "mcpServers".to_string()
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DeclarativeManifest {
    pub driver: DeclarativeDriverSpec,
    #[serde(default)]
    pub skills: Option<DeclarativeSkillsSpec>,
    #[serde(default)]
    pub mcp: Option<DeclarativeMcpSpec>,
}

/// Declarative template emitter dynamically instantiated from emitter.toml
pub struct DeclarativeEmitter {
    pub manifest: DeclarativeManifest,
}

impl DeclarativeEmitter {
    pub fn from_toml(content: &str) -> Result<Self> {
        let manifest: DeclarativeManifest =
            toml::from_str(content).context("Failed to parse declarative emitter manifest TOML")?;
        Ok(Self { manifest })
    }

    pub fn from_file(path: &Path) -> Result<Self> {
        let content = fs::read_to_string(path)
            .with_context(|| format!("Failed to read emitter manifest at {}", path.display()))?;
        Self::from_toml(&content)
    }
}

impl SkillEmitter for DeclarativeEmitter {
    fn id(&self) -> &str {
        &self.manifest.driver.id
    }

    fn capabilities(&self) -> EmitterCapabilities {
        let separate = self
            .manifest
            .skills
            .as_ref()
            .map(|s| s.layout == "per_skill_file")
            .unwrap_or(true);
        let mcp_path = self.manifest.mcp.as_ref().map(|m| m.target_path.clone());
        let layout = self
            .manifest
            .skills
            .as_ref()
            .map(|s| s.layout.clone())
            .unwrap_or_else(|| "per_skill_file".to_string());

        EmitterCapabilities {
            supports_separate_files: separate,
            supports_mcp: self.manifest.mcp.is_some(),
            mcp_config_path: mcp_path,
            skill_layout: layout,
        }
    }

    fn emit(&self, bundle: &CompiledSkillBundle) -> Result<Vec<EmittedFile>> {
        let mut files = Vec::new();

        if let Some(ref skills_spec) = self.manifest.skills {
            if skills_spec.layout == "single_markdown_file" {
                let target_path = skills_spec.path.as_deref().unwrap_or("INSTRUCTIONS.md");
                let mut content = format!("# Instructions for {}\n\n", bundle.role.role_name);
                for skill in &bundle.skills {
                    content.push_str(&format!("## {}\n\n", skill.name));
                    content.push_str(&skill.body);
                    content.push_str("\n\n---\n\n");
                }
                files.push(EmittedFile {
                    path: PathBuf::from(target_path),
                    content,
                    executable: false,
                });
            } else {
                let pattern = skills_spec
                    .path_pattern
                    .as_deref()
                    .unwrap_or("skills/{name}.md");
                for skill in &bundle.skills {
                    let rel_str = pattern.replace("{name}", &skill.name);
                    let body = if skills_spec.include_frontmatter {
                        render_skill_markdown(skill)
                    } else {
                        skill.body.clone()
                    };
                    files.push(EmittedFile {
                        path: PathBuf::from(rel_str),
                        content: body,
                        executable: false,
                    });
                }
            }
        }

        if let Some(ref mcp_spec) = self.manifest.mcp {
            if !bundle.mcp_servers.is_empty() {
                let mut servers_map = BTreeMap::new();
                for server in &bundle.mcp_servers {
                    servers_map.insert(
                        server.id.clone(),
                        serde_json::json!({
                            "command": server.command,
                            "args": server.args,
                            "env": server.env,
                        }),
                    );
                }

                let content_str = match mcp_spec.schema_wrapper.as_str() {
                    "mcp" => {
                        let obj = serde_json::json!({ "mcp": servers_map });
                        serde_json::to_string_pretty(&obj)?
                    }
                    "none" => serde_json::to_string_pretty(&servers_map)?,
                    _ => {
                        let obj = serde_json::json!({ "mcpServers": servers_map });
                        serde_json::to_string_pretty(&obj)?
                    }
                };

                files.push(EmittedFile {
                    path: PathBuf::from(&mcp_spec.target_path),
                    content: content_str,
                    executable: false,
                });
            }
        }

        Ok(files)
    }
}

// -----------------------------------------------------------------------------
// Command Plugin Emitter (Layer 2)
// -----------------------------------------------------------------------------

/// External executable plugin emitter communicating via stdin/stdout JSON
pub struct CommandEmitter {
    pub id: String,
    pub executable: PathBuf,
    pub args: Vec<String>,
}

impl SkillEmitter for CommandEmitter {
    fn id(&self) -> &str {
        &self.id
    }

    fn capabilities(&self) -> EmitterCapabilities {
        EmitterCapabilities {
            supports_separate_files: true,
            supports_mcp: true,
            mcp_config_path: None,
            skill_layout: "plugin_defined".to_string(),
        }
    }

    fn emit(&self, bundle: &CompiledSkillBundle) -> Result<Vec<EmittedFile>> {
        let bundle_json = bundle.to_json_pretty()?;

        let mut child = Command::new(&self.executable)
            .args(&self.args)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .with_context(|| {
                format!(
                    "Failed to spawn command emitter: {}",
                    self.executable.display()
                )
            })?;

        if let Some(mut stdin) = child.stdin.take() {
            stdin.write_all(bundle_json.as_bytes())?;
        }

        let output = child.wait_with_output().with_context(|| {
            format!(
                "Command emitter failed during execution: {}",
                self.executable.display()
            )
        })?;

        if !output.status.success() {
            let stderr = String::from_utf8_lossy(&output.stderr);
            return Err(anyhow!(
                "Command emitter '{}' exited with status {}: {}",
                self.id,
                output.status,
                stderr
            ));
        }

        let stdout = String::from_utf8_lossy(&output.stdout);
        let files: Vec<EmittedFile> = serde_json::from_str(&stdout).with_context(|| {
            format!(
                "Command emitter '{}' produced invalid EmittedFile JSON output:\n{}",
                self.id, stdout
            )
        })?;

        // Validate all returned paths for path containment
        for f in &files {
            validate_emitted_path(&f.path)?;
        }

        Ok(files)
    }
}

// -----------------------------------------------------------------------------
// Emitter Registry
// -----------------------------------------------------------------------------

/// Detailed descriptor for a registered driver
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DriverInfo {
    pub id: String,
    pub source: String, // "built-in" | "declarative" | "command"
    pub capabilities: EmitterCapabilities,
}

/// Dynamic registry resolving agent emitters across 3 priority layers
pub struct EmitterRegistry {
    declarative: BTreeMap<String, Arc<dyn SkillEmitter>>,
    command: BTreeMap<String, Arc<dyn SkillEmitter>>,
    builtin: BTreeMap<String, Arc<dyn SkillEmitter>>,
}

impl Default for EmitterRegistry {
    fn default() -> Self {
        Self::new()
    }
}

impl EmitterRegistry {
    /// Create registry initialized with built-in Rust emitters
    pub fn new() -> Self {
        let mut builtin: BTreeMap<String, Arc<dyn SkillEmitter>> = BTreeMap::new();
        builtin.insert("pi".to_string(), Arc::new(PiEmitter));
        builtin.insert("claude".to_string(), Arc::new(ClaudeEmitter));
        builtin.insert("opencode".to_string(), Arc::new(OpenCodeEmitter));
        builtin.insert("antigravity".to_string(), Arc::new(AntigravityEmitter));
        builtin.insert("agy".to_string(), Arc::new(AntigravityEmitter));

        Self {
            declarative: BTreeMap::new(),
            command: BTreeMap::new(),
            builtin,
        }
    }

    /// Register a declarative emitter instance
    pub fn register_declarative(&mut self, emitter: DeclarativeEmitter) {
        let id = emitter.id().to_string().to_lowercase();
        self.declarative.insert(id, Arc::new(emitter));
    }

    /// Register an external command plugin emitter
    pub fn register_command(&mut self, id: &str, executable: PathBuf, args: Vec<String>) {
        let emitter = CommandEmitter {
            id: id.to_string(),
            executable,
            args,
        };
        self.command.insert(id.to_lowercase(), Arc::new(emitter));
    }

    /// Discover declarative emitters from packages (e.g. `pa_packages/agents/*/emitter.toml`)
    pub fn discover_declarative(&mut self, packages_dir: &Path) -> Result<()> {
        let agents_dir = packages_dir.join("agents");
        if agents_dir.is_dir() {
            if let Ok(entries) = fs::read_dir(agents_dir) {
                for entry in entries.flatten() {
                    let path = entry.path();
                    if path.is_dir() {
                        let emitter_file = path.join("emitter.toml");
                        if emitter_file.is_file() {
                            if let Ok(emitter) = DeclarativeEmitter::from_file(&emitter_file) {
                                self.register_declarative(emitter);
                            }
                        }
                    }
                }
            }
        }
        Ok(())
    }

    /// Dynamically resolve an emitter for the specified agent ID across layers
    /// Priority:
    ///   Layer 1: Declarative emitters (emitter.toml)
    ///   Layer 2: External Command emitters
    ///   Layer 3: Built-in emitters
    pub fn resolve(&self, agent_id: &str) -> Option<Arc<dyn SkillEmitter>> {
        let key = agent_id.trim().to_lowercase();

        if let Some(emitter) = self.declarative.get(&key) {
            return Some(Arc::clone(emitter));
        }

        if let Some(emitter) = self.command.get(&key) {
            return Some(Arc::clone(emitter));
        }

        if let Some(emitter) = self.builtin.get(&key) {
            return Some(Arc::clone(emitter));
        }

        None
    }

    /// List all registered drivers
    pub fn list_drivers(&self) -> Vec<DriverInfo> {
        let mut drivers = Vec::new();

        // Collect all distinct IDs
        let mut all_ids = std::collections::BTreeSet::new();
        for k in self.declarative.keys() {
            all_ids.insert(k.clone());
        }
        for k in self.command.keys() {
            all_ids.insert(k.clone());
        }
        for k in self.builtin.keys() {
            all_ids.insert(k.clone());
        }

        for id in all_ids {
            if let Some(emitter) = self.resolve(&id) {
                let source = if self.declarative.contains_key(&id) {
                    "declarative".to_string()
                } else if self.command.contains_key(&id) {
                    "command".to_string()
                } else {
                    "built-in".to_string()
                };

                drivers.push(DriverInfo {
                    id: id.clone(),
                    source,
                    capabilities: emitter.capabilities(),
                });
            }
        }

        drivers
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::skills::{McpServerSpec, RoleContext, SKILL_IR_SCHEMA_VERSION};
    use tempfile::tempdir;

    fn sample_bundle() -> CompiledSkillBundle {
        CompiledSkillBundle {
            schema_version: SKILL_IR_SCHEMA_VERSION,
            role: RoleContext {
                role_name: "test_role".to_string(),
                driver: "pi".to_string(),
                model_tier: "frontier".to_string(),
                allowed_write_paths: vec!["src".to_string()],
                skills_merkle_root: "feedface".to_string(),
            },
            skills: vec![SkillDoc {
                name: "test_skill".to_string(),
                description: "Test description".to_string(),
                triggers: vec!["test".to_string()],
                required_mcp: vec![],
                tags: vec!["unit".to_string()],
                body: "Run unit tests carefully.".to_string(),
                sha256: "abcdef123456".to_string(),
                source_path: PathBuf::from("test"),
            }],
            mcp_servers: vec![McpServerSpec {
                id: "telemetry".to_string(),
                transport: "stdio".to_string(),
                command: "/usr/bin/telemetry".to_string(),
                args: vec!["--daemon".to_string()],
                env: BTreeMap::new(),
                read_only: true,
            }],
        }
    }

    #[test]
    fn test_pi_emitter_output() {
        let emitter = PiEmitter;
        let bundle = sample_bundle();
        let files = emitter.emit(&bundle).unwrap();
        assert_eq!(files.len(), 2);

        let skill_file = files
            .iter()
            .find(|f| f.path == Path::new(".pi/skills/test_skill/SKILL.md"))
            .unwrap();
        assert!(skill_file.content.contains("name: test_skill"));
        assert!(skill_file.content.contains("Run unit tests carefully."));

        let mcp_file = files
            .iter()
            .find(|f| f.path == Path::new(".pi/mcp.json"))
            .unwrap();
        assert!(mcp_file.content.contains("telemetry"));
        assert!(mcp_file.content.contains("/usr/bin/telemetry"));
    }

    #[test]
    fn test_claude_emitter_output() {
        let emitter = ClaudeEmitter;
        let bundle = sample_bundle();
        let files = emitter.emit(&bundle).unwrap();
        assert_eq!(files.len(), 3);

        assert!(files.iter().any(|f| f.path == Path::new("CLAUDE.md")));
        assert!(files
            .iter()
            .any(|f| f.path == Path::new(".claude/rules/test_skill.md")));
        assert!(files.iter().any(|f| f.path == Path::new(".claude.json")));
    }

    #[test]
    fn test_opencode_emitter_output() {
        let emitter = OpenCodeEmitter;
        let bundle = sample_bundle();
        let files = emitter.emit(&bundle).unwrap();
        assert_eq!(files.len(), 3);

        assert!(files
            .iter()
            .any(|f| f.path == Path::new(".opencode/instructions.md")));
        assert!(files
            .iter()
            .any(|f| f.path == Path::new(".config/opencode/skills/test_skill.md")));
        let mcp_file = files
            .iter()
            .find(|f| f.path == Path::new(".config/opencode/opencode.json"))
            .unwrap();
        assert!(mcp_file.content.contains("\"type\": \"local\""));
    }

    #[test]
    fn test_antigravity_emitter_output() {
        let emitter = AntigravityEmitter;
        let bundle = sample_bundle();
        let files = emitter.emit(&bundle).unwrap();
        assert_eq!(files.len(), 2);

        assert!(files
            .iter()
            .any(|f| f.path == Path::new(".gemini/skills/test_skill/SKILL.md")));
        assert!(files
            .iter()
            .any(|f| f.path == Path::new(".gemini/antigravity/mcp_config.json")));
    }

    #[test]
    fn test_path_traversal_prevention() {
        assert!(validate_emitted_path(Path::new("valid/path.md")).is_ok());
        assert!(validate_emitted_path(Path::new("../escape.md")).is_err());
        assert!(validate_emitted_path(Path::new("subdir/../../escape.md")).is_err());
        assert!(validate_emitted_path(Path::new("/etc/passwd")).is_err());
    }

    #[test]
    fn test_declarative_emitter_parsing_and_emission() {
        let toml_content = r#"
[driver]
id = "cursor"
description = "Cursor IDE declarative emitter"

[skills]
layout = "per_skill_file"
path_pattern = ".cursor/rules/{name}.mdc"
include_frontmatter = true

[mcp]
target_path = ".cursor/mcp.json"
format = "json"
schema_wrapper = "mcpServers"
"#;
        let emitter = DeclarativeEmitter::from_toml(toml_content).unwrap();
        assert_eq!(emitter.id(), "cursor");

        let bundle = sample_bundle();
        let files = emitter.emit(&bundle).unwrap();
        assert_eq!(files.len(), 2);

        let rule_file = files
            .iter()
            .find(|f| f.path == Path::new(".cursor/rules/test_skill.mdc"))
            .unwrap();
        assert!(rule_file.content.contains("name: test_skill"));

        let mcp_file = files
            .iter()
            .find(|f| f.path == Path::new(".cursor/mcp.json"))
            .unwrap();
        assert!(mcp_file.content.contains("mcpServers"));
    }

    #[test]
    fn test_emitter_registry_layer_precedence() {
        let mut registry = EmitterRegistry::new();

        // 1. Builtin resolution
        let pi = registry.resolve("pi").unwrap();
        assert_eq!(pi.id(), "pi");

        // 2. Override with declarative
        let toml_override = r#"
[driver]
id = "pi"
description = "Custom Declarative Pi"

[skills]
layout = "single_markdown_file"
path = "PI_CUSTOM.md"
"#;
        let decl = DeclarativeEmitter::from_toml(toml_override).unwrap();
        registry.register_declarative(decl);

        let resolved = registry.resolve("pi").unwrap();
        let caps = resolved.capabilities();
        assert_eq!(caps.skill_layout, "single_markdown_file");
    }

    #[test]
    fn test_write_staged_files_safety() {
        let temp = tempdir().unwrap();
        let staging_root = temp.path().join("staging");

        let files = vec![
            EmittedFile {
                path: PathBuf::from("dir1/file.txt"),
                content: "hello world".to_string(),
                executable: false,
            },
            EmittedFile {
                path: PathBuf::from("script.sh"),
                content: "#!/bin/sh\necho ok".to_string(),
                executable: true,
            },
        ];

        let written = write_staged_files(&staging_root, &files).unwrap();
        assert_eq!(written.len(), 2);
        assert!(staging_root.join("dir1/file.txt").is_file());
        assert!(staging_root.join("script.sh").is_file());

        // Attempting to write a traversing path fails closed
        let bad_files = vec![EmittedFile {
            path: PathBuf::from("../escape.txt"),
            content: "evil".to_string(),
            executable: false,
        }];
        assert!(write_staged_files(&staging_root, &bad_files).is_err());
    }

    #[test]
    fn test_emitter_conformance_suite_all_emitters() {
        let temp = tempdir().unwrap();
        let bundle = sample_bundle();

        // 1. Prepare emitters: 4 built-ins + 1 declarative + 1 command plugin
        let decl_toml = r#"
[driver]
id = "mock-declarative"
description = "Mock Declarative"

[skills]
layout = "per_skill_file"
path_pattern = ".mock/skills/{name}.md"

[mcp]
target_path = ".mock/mcp.json"
format = "json"
schema_wrapper = "mcpServers"
"#;
        let decl_emitter = DeclarativeEmitter::from_toml(decl_toml).unwrap();

        // Create a mock plugin script that echoes valid EmittedFile JSON
        let plugin_script = temp.path().join("mock_plugin.sh");
        fs::write(
            &plugin_script,
            r##"#!/bin/sh
cat << 'EOF'
[{"path": ".plugin/instructions.md", "content": "# Plugin Instructions\n", "executable": false}]
EOF
"##,
        )
        .unwrap();
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            fs::set_permissions(&plugin_script, fs::Permissions::from_mode(0o755)).unwrap();
        }

        let cmd_emitter = CommandEmitter {
            id: "mock-command".to_string(),
            executable: plugin_script,
            args: vec![],
        };

        let emitters: Vec<Box<dyn SkillEmitter>> = vec![
            Box::new(PiEmitter),
            Box::new(ClaudeEmitter),
            Box::new(OpenCodeEmitter),
            Box::new(AntigravityEmitter),
            Box::new(decl_emitter),
            Box::new(cmd_emitter),
        ];

        for emitter in emitters {
            let id = emitter.id();

            // Property 1: Determinism across repeated runs
            let run1 = emitter.emit(&bundle).unwrap();
            let run2 = emitter.emit(&bundle).unwrap();
            assert_eq!(run1, run2, "Determinism failed for emitter: {}", id);

            // Property 2: Path-containment & security checks
            for f in &run1 {
                assert!(
                    validate_emitted_path(&f.path).is_ok(),
                    "Path traversal check failed for emitter {} on path: {}",
                    id,
                    f.path.display()
                );
                assert!(
                    !f.content.contains("RAW_SECRET_KEY"),
                    "Secret leakage check failed for emitter {}",
                    id
                );
            }

            // Property 3: Staging write success
            let stage_dir = temp.path().join(format!("stage_{}", id));
            let written = write_staged_files(&stage_dir, &run1).unwrap();
            assert_eq!(
                written.len(),
                run1.len(),
                "Staging write count mismatch for emitter {}",
                id
            );
        }
    }
}
