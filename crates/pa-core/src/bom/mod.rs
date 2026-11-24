pub mod canonical;
pub mod collectors;
pub mod diff;
pub mod formats;
pub mod models;
pub mod policy;
pub mod signing;

use anyhow::Result;
use ed25519_dalek::SigningKey;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

pub use canonical::{compute_canonical_sha256, to_canonical_json_bytes, to_canonical_json_string};
pub use models::*;
pub use signing::{
    derive_key_id, generate_keypair, load_or_create_signing_key, sign_factory_bom, sign_payload,
    verify_factory_bom, verify_signature,
};

pub struct BomBuilder {
    pub target_name: String,
    pub target_version: String,
    pub root_dir: PathBuf,
    pub task_id: Option<String>,
    pub trace_id: Option<String>,
    pub commit_sha: Option<String>,
    pub agent_name: Option<String>,
    pub task_prompt: Option<String>,
    pub model: Option<String>,
    pub backend: String,
    pub artifact_paths: Vec<PathBuf>,
}

impl BomBuilder {
    pub fn new(target_name: impl Into<String>, target_version: impl Into<String>) -> Self {
        Self {
            target_name: target_name.into(),
            target_version: target_version.into(),
            root_dir: PathBuf::from("."),
            task_id: None,
            trace_id: None,
            commit_sha: None,
            agent_name: None,
            task_prompt: None,
            model: None,
            backend: "auto".to_string(),
            artifact_paths: Vec::new(),
        }
    }

    pub fn with_root_dir(mut self, path: impl Into<PathBuf>) -> Self {
        self.root_dir = path.into();
        self
    }

    pub fn with_task_id(mut self, id: impl Into<String>) -> Self {
        self.task_id = Some(id.into());
        self
    }

    pub fn with_trace_id(mut self, id: impl Into<String>) -> Self {
        self.trace_id = Some(id.into());
        self
    }

    pub fn with_commit_sha(mut self, sha: impl Into<String>) -> Self {
        self.commit_sha = Some(sha.into());
        self
    }

    pub fn with_agent_name(mut self, name: impl Into<String>) -> Self {
        self.agent_name = Some(name.into());
        self
    }

    pub fn with_task_prompt(mut self, prompt: impl Into<String>) -> Self {
        self.task_prompt = Some(prompt.into());
        self
    }

    pub fn with_model(mut self, model: impl Into<String>) -> Self {
        self.model = Some(model.into());
        self
    }

    pub fn with_backend(mut self, backend: impl Into<String>) -> Self {
        self.backend = backend.into();
        self
    }

    pub fn with_artifact_paths(mut self, paths: Vec<PathBuf>) -> Self {
        self.artifact_paths = paths;
        self
    }

    pub fn build(self) -> Result<FactoryBom> {
        let bom_id = format!(
            "bom-{}-{}",
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap_or_default()
                .as_secs(),
            hex::encode(rand::random::<[u8; 4]>())
        );

        let created_at = {
            let duration = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap_or_default();
            let secs = duration.as_secs();
            // Basic ISO 8601 UTC string format: YYYY-MM-DDTHH:MM:SSZ
            // Using a simple deterministic UTC formatter
            format_timestamp_utc(secs)
        };

        let originating_machine = collectors::substrate::collect_machine_identity();
        let plane_dependencies = collectors::dependencies::collect_dependencies(&self.root_dir)?;
        let plane_toolchain = collectors::toolchain::collect_host_toolchain()?;
        let plane_substrate = collectors::substrate::collect_substrate_environment(&self.backend);
        let plane_agentic = collectors::agentic::collect_agentic_supply_chain(
            &self.root_dir,
            self.agent_name.as_deref(),
            self.task_prompt.as_deref(),
            self.model.as_deref(),
        );
        let plane_proxy = collectors::proxy::collect_proxy_supply_chain(&self.root_dir);
        let plane_specs = collectors::specs::collect_spec_strategy_supply_chain(&self.root_dir);
        let artifacts = collectors::artifacts::collect_artifacts(&self.artifact_paths);

        Ok(FactoryBom {
            bom_id,
            created_at,
            target_name: self.target_name,
            target_version: self.target_version,
            task_id: self.task_id,
            trace_id: self.trace_id,
            commit_sha: self.commit_sha,
            originating_machine,
            plane_dependencies,
            plane_toolchain,
            plane_substrate,
            plane_agentic,
            plane_proxy,
            plane_specs,
            artifacts,
            signature_info: None,
        })
    }

    pub fn build_and_sign(self, signing_key: &SigningKey) -> Result<(FactoryBom, String, String)> {
        let bom = self.build()?;
        sign_factory_bom(bom, signing_key)
    }
}

pub fn format_timestamp_utc(secs: u64) -> String {
    // Days since UNIX epoch
    let days = secs / 86400;
    let time_of_day = secs % 86400;
    let hours = time_of_day / 3600;
    let minutes = (time_of_day % 3600) / 60;
    let seconds = time_of_day % 60;

    // Convert days since 1970-01-01 to year, month, day
    let mut year = 1970;
    let mut rem_days = days;
    loop {
        let leap = is_leap_year(year);
        let days_in_year = if leap { 366 } else { 365 };
        if rem_days < days_in_year {
            break;
        }
        rem_days -= days_in_year;
        year += 1;
    }

    let days_in_months = [
        31,
        if is_leap_year(year) { 29 } else { 28 },
        31,
        30,
        31,
        30,
        31,
        31,
        30,
        31,
        30,
        31,
    ];
    let mut month = 1;
    for &dim in &days_in_months {
        if rem_days < dim {
            break;
        }
        rem_days -= dim;
        month += 1;
    }
    let day = rem_days + 1;

    format!(
        "{:04}-{:02}-{:02}T{:02}:{:02}:{:02}Z",
        year, month, day, hours, minutes, seconds
    )
}

fn is_leap_year(y: u64) -> bool {
    (y.is_multiple_of(4) && !y.is_multiple_of(100)) || y.is_multiple_of(400)
}

#[derive(Debug, Clone)]
pub struct BomStoragePaths {
    pub cdx_path: PathBuf,
    pub slsa_path: PathBuf,
    pub canonical_path: PathBuf,
    pub sig_path: PathBuf,
}

pub fn persist_factory_bom(
    bom: &FactoryBom,
    base_dir: &Path,
    store: Option<&dyn crate::storage::FactoryAnalyticsStore>,
) -> Result<BomStoragePaths> {
    let boms_dir = base_dir.join(".pa/boms");
    std::fs::create_dir_all(&boms_dir)?;

    let cdx_path = boms_dir.join(format!("{}.cdx.json", bom.bom_id));
    let slsa_path = boms_dir.join(format!("{}.slsa.json", bom.bom_id));
    let canonical_path = boms_dir.join(format!("{}.canonical.json", bom.bom_id));
    let sig_path = boms_dir.join(format!("{}.sig", bom.bom_id));

    // 1. Write canonical JSON
    let canonical_bytes = to_canonical_json_bytes(bom)?;
    std::fs::write(&canonical_path, &canonical_bytes)?;

    // 2. Write CycloneDX 1.6 JSON
    let cdx_json = formats::to_cyclonedx_json(bom)?;
    std::fs::write(&cdx_path, serde_json::to_string_pretty(&cdx_json)?)?;

    // 3. Write SLSA DSSE JSON
    let slsa_json = formats::to_slsa_dsse_json(bom)?;
    std::fs::write(&slsa_path, serde_json::to_string_pretty(&slsa_json)?)?;

    // 4. Write signature
    if let Some(ref sig_info) = bom.signature_info {
        std::fs::write(&sig_path, format!("{}\n", sig_info.signature_b64))?;
    }

    // Set read-only permissions (0444) on unix
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let perms = std::fs::Permissions::from_mode(0o444);
        let _ = std::fs::set_permissions(&canonical_path, perms.clone());
        let _ = std::fs::set_permissions(&cdx_path, perms.clone());
        let _ = std::fs::set_permissions(&slsa_path, perms.clone());
        let _ = std::fs::set_permissions(&sig_path, perms);
    }

    // 5. Relational index in SQLite store if provided
    if let Some(st) = store {
        st.record_bom(bom, &cdx_path, &slsa_path, &canonical_path)?;
    }

    Ok(BomStoragePaths {
        cdx_path,
        slsa_path,
        canonical_path,
        sig_path,
    })
}
