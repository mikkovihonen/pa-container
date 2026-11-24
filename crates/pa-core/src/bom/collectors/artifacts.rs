use sha2::{Digest, Sha256, Sha512};
use std::fs;
use std::path::{Path, PathBuf};

use crate::bom::models::OutputArtifact;

pub fn collect_artifacts(paths: &[PathBuf]) -> Vec<OutputArtifact> {
    let mut artifacts = Vec::new();

    for path in paths {
        if path.is_file() {
            if let Some(art) = process_file(path) {
                artifacts.push(art);
            }
        } else if path.is_dir() {
            if let Ok(entries) = fs::read_dir(path) {
                for entry in entries.flatten() {
                    let p = entry.path();
                    if p.is_file() {
                        if let Some(art) = process_file(&p) {
                            artifacts.push(art);
                        }
                    }
                }
            }
        }
    }

    artifacts.sort_by(|a, b| a.name.cmp(&b.name));
    artifacts
}

fn process_file(path: &Path) -> Option<OutputArtifact> {
    let bytes = fs::read(path).ok()?;
    let size_bytes = bytes.len() as u64;

    let mut sha256_hasher = Sha256::new();
    sha256_hasher.update(&bytes);
    let sha256 = hex::encode(sha256_hasher.finalize());

    let mut sha512_hasher = Sha512::new();
    sha512_hasher.update(&bytes);
    let sha512 = hex::encode(sha512_hasher.finalize());

    let name = path
        .file_name()
        .unwrap_or_default()
        .to_string_lossy()
        .to_string();
    let ext = path
        .extension()
        .unwrap_or_default()
        .to_string_lossy()
        .to_lowercase();

    let (artifact_type, mime_type) = match ext.as_str() {
        "tar" | "gz" | "tgz" | "zip" => ("archive", Some("application/zip")),
        "whl" => ("package", Some("application/x-wheel+zip")),
        "deb" | "rpm" => ("package", Some("application/octet-stream")),
        "json" => ("metadata", Some("application/json")),
        "" => ("binary", Some("application/octet-stream")),
        _ => ("bundle", Some("application/octet-stream")),
    };

    Some(OutputArtifact {
        name,
        path: path.to_string_lossy().to_string(),
        sha256,
        sha512,
        size_bytes,
        mime_type: mime_type.map(|s| s.to_string()),
        artifact_type: artifact_type.to_string(),
    })
}
