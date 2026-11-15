# Platform Feature Parity Reference: macOS & Linux

PA-Container 2.0 is designed from the ground up to ensure declarative software factories (`factory.toml`) run with full behavioral, security, and performance parity across both macOS (Apple Silicon) and Linux (KVM / Containers).

---

## 1. 1:1 Primitive Equivalency Matrix

Each operational domain maps to an operating system-native primitive:

| Capability Domain | macOS Implementation | Linux Implementation | Parity Guarantee |
| :--- | :--- | :--- | :--- |
| **Virtualization Backend** | Tart (`Virtualization.framework` / Apple IPSW) | Incus / LXD (KVM / Fedora 45 cloud image) | Identical lifecycle commands (`up`, `down`, `status`) |
| **Hypervisor Contract** | `TartMacOSBackend` (`impl FactoryBackend`) | `IncusLinuxBackend` (`impl FactoryBackend`) | Shared Rust trait with contract assertions |
| **In-Guest Daemon** | `pa-agentd` (JSON-RPC 2.0 over stdio) | `pa-agentd` (JSON-RPC 2.0 over stdio) | Identical RPC method schemas & responses |
| **Process Sandboxing** | macOS Seatbelt (`sandbox-exec` / `.sb`) | Landlock ABI v4+ (`pa-landlock`) + `bwrap` | Strict isolation to workspace & read-only system |
| **GPU / AI Compute** | ParavirtualizedGraphics + Metal Interposer Shim (`TartMetalCapabilities.dylib`) | Direct device node passthrough (`/dev/dri`, `/dev/kfd`, `/dev/nvidia*`) | Full acceleration for LLM kernels (MLX, `llama.cpp`) |
| **Storage Resizing** | Dynamic APFS container expansion (`diskutil apfs resizeContainer`) | Dynamic filesystem detection & expansion (`btrfs`, `xfs`, `growpart` + `resize2fs`) | Automatically claims expanded host virtual disk |
| **Cache & Disk Pruning** | APFS container defragmentation + cache purge | Package cache cleanup (`dnf5 clean all`, `apt-get clean`) + `fstrim` | Sparse disk compaction prior to VM shutdown |
| **Headless OS Tuning** | Spotlight off, Sleep off, CrashReporter off, Gatekeeper off | Systemd sleep inhibitors, PackageKit disable, swappiness tuning | Eliminates background CPU and disk contention |
| **Zero-Port Egress & Proxy** | `pf` (Packet Filter) anchor redirection + UDS proxy | `nftables` tables/chains redirection + UDS proxy | Zero open host TCP ports, per-agent port isolation |
| **User & UID Isolation** | Directory Services (`dscl`, `dseditgroup`) | Shadow suite (`useradd -u 2001 -m -s /bin/bash`) | Mandatory unprivileged agent execution ($\text{UID} \ge 2001$) |
| **Deterministic Toolchains** | Homebrew non-interactive (`HOMEBREW_NO_ANALYTICS=1`) | `dnf5` non-interactive (`-y --nodocs`) | Headless automated package provisioning |

---

## 2. Multi-Platform Continuous Integration

To prevent platform drift between macOS and Linux implementations, GitHub Actions executes continuous integration across a dual-OS matrix in [.github/workflows/ci.yml](file:///.github/workflows/ci.yml):

```yaml
strategy:
    fail-fast: false
    matrix:
        os: [ubuntu-latest, macos-14]
```

Every pull request and push to `main` verifies:
- **`cargo fmt`**: Consistent code style across all crates.
- **`cargo clippy`**: Compiler warnings treated as errors on both OSes.
- **`cargo test --workspace`**: Unit and integration test suites executed on native Linux x86_64 and native Apple Silicon M1/M2 runners.

---

## 3. Generic Backend Conformance Suite

In `crates/pa-core`, both backends are verified against the shared conformance test `assert_backend_conformance`:

```rust
pub fn assert_backend_conformance<B: FactoryBackend + ?Sized>(
    backend: &B,
    config: &crate::schema::FactoryConfig,
) {
    let proxy_ip = backend.start_proxy(config).expect("Proxy start must succeed");
    assert!(!proxy_ip.is_empty(), "Proxy gateway IP must not be empty");

    let cache_dir = dirs_fallback_cache();
    let proxy_cfg_path = cache_dir.join("proxy_config.json");
    assert!(proxy_cfg_path.exists(), "Proxy configuration file must be generated");
}
```

This guarantees:
- Identical JSON status schemas (`backend`, `vm_name`, `proxy_host_ip`, `guest`).
- Symmetrical proxy configuration and per-agent routing rules.
- HMAC session placeholder token synthesis.

---

## 4. In-Guest Dynamic Storage & Tuning Parity

Inside the factory microVM, `pa-agentd` executes platform-appropriate logic behind identical JSON-RPC methods:

### Dynamic Disk Expansion (`resize_disk`)
- **macOS:** Dynamically queries `diskutil info /` to locate the synthesized APFS container (`disk3`) and executes `diskutil apfs resizeContainer disk3 0`.
- **Linux:** Dynamically detects root mount source and filesystem type via `findmnt` / `/proc/mounts`:
    - **Btrfs:** `btrfs filesystem resize max /`
    - **XFS:** `xfs_growfs /`
    - **ext4 / ext3:** Parses block device (`/dev/sda1`, `/dev/vda2`, `/dev/nvme0n1p1`), runs `growpart`, and executes `resize2fs`.

### Headless Performance Tuning (`apply_tuning`)
- **macOS:** Disables Spotlight indexing (`mdutil`), disables computer and display sleep (`systemsetup`), disables CrashReporter dialogs, and disables Gatekeeper quarantine.
- **Linux:** Masks systemd sleep and hibernate targets (`sleep.target`, `suspend.target`, `hibernate.target`), disables `packagekit.service`, tunes `vm.swappiness=10`, and disables redundant cloud-init polling.

---

## 5. End-to-End Golden Workflows

The automated test script [tests/e2e/test_factory_lifecycle.sh](file:///Users/mikkovihonen/Workspace/pi-container/tests/e2e/test_factory_lifecycle.sh) validates the end-to-end software factory lifecycle:
1. `pa factory status`: Verifies hypervisor responsiveness and JSON status schema.
2. `pa run`: Spawns sandboxed agent, checks network redirection through `coding-agent-proxy`, and commits code into the Copy-on-Write Git vault.
3. `pa review`: Validates atomic branch namespacing (`refs/heads/pa/{agent}/*`).
4. `pa factory down`: Reverts host configurations and safely halts the microVM.
