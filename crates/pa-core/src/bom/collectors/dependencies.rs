use anyhow::Result;
use std::fs;
use std::path::Path;

use crate::bom::models::{DependencyComponent, DependencyType};

pub fn collect_dependencies(root_dir: &Path) -> Result<Vec<DependencyComponent>> {
    let mut deps = Vec::new();

    // 1. Cargo.lock
    let cargo_lock = root_dir.join("Cargo.lock");
    if cargo_lock.is_file() {
        if let Ok(content) = fs::read_to_string(&cargo_lock) {
            parse_cargo_lock(&content, &mut deps);
        }
    }

    // 2. uv.lock
    let uv_lock = root_dir.join("uv.lock");
    if uv_lock.is_file() {
        if let Ok(content) = fs::read_to_string(&uv_lock) {
            parse_uv_lock(&content, &mut deps);
        }
    }

    // 3. package-lock.json
    let npm_lock = root_dir.join("package-lock.json");
    if npm_lock.is_file() {
        if let Ok(content) = fs::read_to_string(&npm_lock) {
            parse_package_lock(&content, &mut deps);
        }
    }

    // Sort deterministically by ecosystem, name, version
    deps.sort_by(|a, b| {
        a.ecosystem
            .cmp(&b.ecosystem)
            .then_with(|| a.name.cmp(&b.name))
            .then_with(|| a.version.cmp(&b.version))
    });
    deps.dedup();

    Ok(deps)
}

fn parse_cargo_lock(content: &str, out: &mut Vec<DependencyComponent>) {
    if let Ok(val) = content.parse::<toml::Value>() {
        if let Some(packages) = val.get("package").and_then(|p| p.as_array()) {
            for pkg in packages {
                let name = match pkg.get("name").and_then(|n| n.as_str()) {
                    Some(n) => n.to_string(),
                    None => continue,
                };
                let version = match pkg.get("version").and_then(|v| v.as_str()) {
                    Some(v) => v.to_string(),
                    None => continue,
                };
                let checksum = pkg
                    .get("checksum")
                    .and_then(|c| c.as_str())
                    .map(|s| s.to_string());
                let source = pkg.get("source").and_then(|s| s.as_str());

                // Derive PURL
                let purl = format!("pkg:cargo/{}@{}", name, version);

                // Source check: if no source or source == "registry+...", mark dep_type
                let dep_type = if source.is_none() {
                    DependencyType::RuntimeDirect
                } else {
                    DependencyType::RuntimeTransitive
                };

                out.push(DependencyComponent {
                    name,
                    version,
                    purl: Some(purl),
                    checksum,
                    dep_type,
                    ecosystem: "cargo".to_string(),
                });
            }
        }
    }
}

fn parse_uv_lock(content: &str, out: &mut Vec<DependencyComponent>) {
    if let Ok(val) = content.parse::<toml::Value>() {
        if let Some(packages) = val.get("package").and_then(|p| p.as_array()) {
            for pkg in packages {
                let name = match pkg.get("name").and_then(|n| n.as_str()) {
                    Some(n) => n.to_string(),
                    None => continue,
                };
                let version = match pkg.get("version").and_then(|v| v.as_str()) {
                    Some(v) => v.to_string(),
                    None => continue,
                };
                let purl = format!("pkg:pypi/{}@{}", name, version);

                out.push(DependencyComponent {
                    name,
                    version,
                    purl: Some(purl),
                    checksum: None,
                    dep_type: DependencyType::RuntimeTransitive,
                    ecosystem: "pypi".to_string(),
                });
            }
        }
    }
}

fn parse_package_lock(content: &str, out: &mut Vec<DependencyComponent>) {
    if let Ok(val) = serde_json::from_str::<serde_json::Value>(content) {
        if let Some(packages) = val.get("packages").and_then(|p| p.as_object()) {
            for (key, pkg) in packages {
                let name = if key.is_empty() {
                    val.get("name").and_then(|n| n.as_str()).unwrap_or("root")
                } else {
                    key.strip_prefix("node_modules/").unwrap_or(key)
                };
                let version = match pkg.get("version").and_then(|v| v.as_str()) {
                    Some(v) => v.to_string(),
                    None => continue,
                };
                let integrity = pkg
                    .get("integrity")
                    .and_then(|i| i.as_str())
                    .map(|s| s.to_string());
                let purl = format!("pkg:npm/{}@{}", name, version);

                out.push(DependencyComponent {
                    name: name.to_string(),
                    version,
                    purl: Some(purl),
                    checksum: integrity,
                    dep_type: DependencyType::RuntimeTransitive,
                    ecosystem: "npm".to_string(),
                });
            }
        }
    }
}
