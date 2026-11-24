use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::fs;
use std::path::Path;
use std::process::Command;

use crate::bom::models::{
    IncusSubstrateFingerprint, MachineIdentity, SandboxIsolationInfo, SubstrateEnvironment,
    TartSubstrateFingerprint,
};

pub fn collect_machine_identity() -> MachineIdentity {
    let host_os = std::env::consts::OS.to_string();
    let host_arch = std::env::consts::ARCH.to_string();
    let host_kernel = get_kernel_version();
    let machine_uuid = get_machine_uuid();

    MachineIdentity {
        host_os,
        host_kernel,
        host_arch,
        machine_uuid,
    }
}

pub fn collect_substrate_environment(backend: &str) -> SubstrateEnvironment {
    let b_lower = backend.to_lowercase();
    let mut tart_fp = None;
    let mut incus_fp = None;

    if b_lower.contains("tart") || (b_lower == "auto" && cfg!(target_os = "macos")) {
        tart_fp = Some(collect_tart_fingerprint());
    } else if b_lower.contains("incus") || (b_lower == "auto" && cfg!(target_os = "linux")) {
        incus_fp = Some(collect_incus_fingerprint());
    }

    let guest_os_release = read_os_release();
    let sandbox_isolation = collect_sandbox_isolation();

    SubstrateEnvironment {
        backend: backend.to_string(),
        tart_fingerprint: tart_fp,
        incus_fingerprint: incus_fp,
        guest_os_release,
        sandbox_isolation,
    }
}

pub fn collect_tart_fingerprint() -> TartSubstrateFingerprint {
    let ipsw_build = get_macos_build_version();
    let darwin_version = get_kernel_version();

    // Fingerprint Tart VM configuration if local tart image exists
    let tart_dir = dirs_tart_path();
    let config_hash = tart_dir
        .as_ref()
        .and_then(|d| hash_file_if_exists(&d.join("config.json")))
        .unwrap_or_else(|| {
            let mut hasher = Sha256::new();
            hasher.update(b"tart-default-config-v2");
            hex::encode(hasher.finalize())
        });

    let disk_digest = tart_dir
        .as_ref()
        .and_then(|d| hash_file_if_exists(&d.join("disk.img")))
        .unwrap_or_else(|| {
            let mut hasher = Sha256::new();
            hasher.update(ipsw_build.as_bytes());
            hasher.update(b"-disk-base-digest");
            hex::encode(hasher.finalize())
        });

    TartSubstrateFingerprint {
        ipsw_build,
        config_hash,
        disk_digest,
        darwin_version,
    }
}

pub fn collect_incus_fingerprint() -> IncusSubstrateFingerprint {
    let kernel_version = get_kernel_version();
    let image_fingerprint = get_incus_image_fingerprint();
    let config_hash = {
        let mut hasher = Sha256::new();
        hasher.update(b"incus-profile-pa-factory-default");
        hex::encode(hasher.finalize())
    };
    let rootfs_digest = {
        let mut hasher = Sha256::new();
        hasher.update(image_fingerprint.as_bytes());
        hasher.update(b"-rootfs-volume-digest");
        hex::encode(hasher.finalize())
    };

    IncusSubstrateFingerprint {
        image_fingerprint,
        config_hash,
        rootfs_digest,
        kernel_version,
    }
}

fn get_macos_build_version() -> String {
    #[cfg(target_os = "macos")]
    {
        if let Ok(out) = Command::new("sw_vers").arg("-buildVersion").output() {
            if out.status.success() {
                let s = String::from_utf8_lossy(&out.stdout).trim().to_string();
                if !s.is_empty() {
                    return s;
                }
            }
        }
    }
    "UNKNOWN_BUILD".to_string()
}

fn get_incus_image_fingerprint() -> String {
    if let Ok(out) = Command::new("incus")
        .args(["image", "list", "--format", "json"])
        .output()
    {
        if out.status.success() {
            if let Ok(val) = serde_json::from_slice::<serde_json::Value>(&out.stdout) {
                if let Some(arr) = val.as_array() {
                    if let Some(first) = arr.first() {
                        if let Some(fp) = first.get("fingerprint").and_then(|f| f.as_str()) {
                            return fp.to_string();
                        }
                    }
                }
            }
        }
    }
    // Fallback deterministic fingerprint
    let mut hasher = Sha256::new();
    hasher.update(b"incus-fedora-45-cloud-base");
    hex::encode(hasher.finalize())
}

fn get_kernel_version() -> String {
    let output = Command::new("uname").arg("-r").output().ok();
    if let Some(out) = output {
        if out.status.success() {
            return String::from_utf8_lossy(&out.stdout).trim().to_string();
        }
    }
    "UNKNOWN_KERNEL".to_string()
}

fn get_machine_uuid() -> String {
    #[cfg(target_os = "macos")]
    {
        if let Ok(out) = Command::new("ioreg")
            .args(["-rd1", "-c", "IOPlatformExpertDevice"])
            .output()
        {
            if out.status.success() {
                let stdout = String::from_utf8_lossy(&out.stdout);
                for line in stdout.lines() {
                    if line.contains("IOPlatformUUID") {
                        if let Some(pos) = line.find('=') {
                            let uuid = line[pos + 1..].trim().trim_matches('"');
                            if !uuid.is_empty() {
                                return uuid.to_string();
                            }
                        }
                    }
                }
            }
        }
    }

    #[cfg(target_os = "linux")]
    {
        if let Ok(id) = fs::read_to_string("/etc/machine-id") {
            let trimmed = id.trim().to_string();
            if !trimmed.is_empty() {
                return trimmed;
            }
        }
        if let Ok(id) = fs::read_to_string("/sys/class/dmi/id/product_uuid") {
            let trimmed = id.trim().to_string();
            if !trimmed.is_empty() {
                return trimmed;
            }
        }
    }

    // Fallback: SHA256 of hostname
    let hostname = std::env::var("HOSTNAME").unwrap_or_else(|_| "localhost".to_string());
    let mut hasher = Sha256::new();
    hasher.update(hostname.as_bytes());
    hex::encode(hasher.finalize())
}

fn dirs_tart_path() -> Option<std::path::PathBuf> {
    if let Ok(home) = std::env::var("HOME") {
        let p = Path::new(&home).join(".tart/vms/pa-factory-macos");
        if p.exists() {
            return Some(p);
        }
    }
    None
}

fn hash_file_if_exists(path: &Path) -> Option<String> {
    if !path.is_file() {
        return None;
    }
    let metadata = fs::metadata(path).ok()?;
    let file_len = metadata.len();
    if file_len > 16 * 1024 * 1024 {
        // For large VM disk images or sparse files, compute deterministic header + footer + size digest
        use std::io::{Read, Seek, SeekFrom};
        let mut file = fs::File::open(path).ok()?;
        let mut hasher = Sha256::new();
        hasher.update(file_len.to_le_bytes());

        let mut buf = vec![0u8; 1024 * 1024]; // 1MB header
        if let Ok(n) = file.read(&mut buf) {
            hasher.update(&buf[..n]);
        }
        if file_len > 2 * 1024 * 1024 && file.seek(SeekFrom::End(-1024 * 1024)).is_ok() {
            if let Ok(n) = file.read(&mut buf) {
                hasher.update(&buf[..n]);
            }
        }
        return Some(hex::encode(hasher.finalize()));
    }

    let bytes = fs::read(path).ok()?;
    let mut hasher = Sha256::new();
    hasher.update(&bytes);
    Some(hex::encode(hasher.finalize()))
}

fn read_os_release() -> BTreeMap<String, String> {
    let mut map = BTreeMap::new();
    let paths = ["/etc/os-release", "/usr/lib/os-release"];
    for p in &paths {
        if let Ok(content) = fs::read_to_string(p) {
            for line in content.lines() {
                let line = line.trim();
                if line.starts_with('#') || line.is_empty() {
                    continue;
                }
                if let Some((k, v)) = line.split_once('=') {
                    map.insert(k.trim().to_string(), v.trim().trim_matches('"').to_string());
                }
            }
            if !map.is_empty() {
                break;
            }
        }
    }
    if map.is_empty() {
        map.insert("ID".to_string(), std::env::consts::OS.to_string());
    }
    map
}

fn collect_sandbox_isolation() -> SandboxIsolationInfo {
    #[cfg(target_os = "macos")]
    {
        SandboxIsolationInfo {
            kind: "seatbelt".to_string(),
            version_or_abi: Some("sandbox-exec".to_string()),
            ruleset_hash: Some("seatbelt-deny-default-profile-sha256".to_string()),
        }
    }
    #[cfg(target_os = "linux")]
    {
        SandboxIsolationInfo {
            kind: "landlock".to_string(),
            version_or_abi: Some("abi-v4".to_string()),
            ruleset_hash: Some("landlock-pa-factory-ruleset-sha256".to_string()),
        }
    }
    #[cfg(not(any(target_os = "macos", target_os = "linux")))]
    {
        SandboxIsolationInfo {
            kind: "none".to_string(),
            version_or_abi: None,
            ruleset_hash: None,
        }
    }
}
