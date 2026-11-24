use std::path::PathBuf;

/// Canonical cache directory for PA-Container runtime artifacts
pub fn cache_dir() -> PathBuf {
    if let Ok(dir) = std::env::var("PA_CACHE_DIR") {
        return PathBuf::from(dir);
    }
    if let Ok(home) = std::env::var("HOME") {
        PathBuf::from(home).join(".cache").join("pa-container")
    } else {
        std::env::temp_dir().join("pa-container")
    }
}

/// Canonical state directory for PA-Container compute and runtime daemons
pub fn state_dir() -> PathBuf {
    if let Ok(dir) = std::env::var("PA_COMPUTE_STATE_DIR") {
        return PathBuf::from(dir);
    }
    if let Ok(home) = std::env::var("HOME") {
        PathBuf::from(home)
            .join(".local")
            .join("state")
            .join("pa-container")
            .join("compute")
    } else {
        std::env::temp_dir()
            .join("pa-container-state")
            .join("compute")
    }
}

/// Canonical logs directory for PA-Container background servers
pub fn logs_dir() -> PathBuf {
    if let Ok(dir) = std::env::var("PA_COMPUTE_LOG_DIR") {
        return PathBuf::from(dir);
    }
    if let Ok(home) = std::env::var("HOME") {
        PathBuf::from(home)
            .join(".local")
            .join("state")
            .join("pa-container")
            .join("logs")
    } else {
        std::env::temp_dir().join("pa-container-state").join("logs")
    }
}

/// Canonical share directory for PA-Container managed binaries and assets
pub fn share_dir() -> PathBuf {
    if let Ok(dir) = std::env::var("PA_COMPUTE_BIN_DIR") {
        return PathBuf::from(dir);
    }
    if let Ok(home) = std::env::var("HOME") {
        PathBuf::from(home)
            .join(".local")
            .join("share")
            .join("pa-container")
            .join("bin")
    } else {
        std::env::temp_dir().join("pa-container-share").join("bin")
    }
}
