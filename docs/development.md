# Development Guide: PA-Container 2.0

PA-Container 2.0 is developed as a hybrid Rust and Python workspace. Core hypervisor orchestration, guest daemons, sandboxing primitives, and CLI commands are implemented in Rust. Network proxy extensions are implemented in Python for `mitmproxy`.

---

## 1. Development Prerequisites

- **Rust 1.85+:** Managed via `rustup`. Ensure `clippy` and `rustfmt` are installed:
  ```bash
  rustup component add clippy rustfmt
  ```
- **Python 3.14+ with uv:**
  ```bash
  uv sync
  ```
- **Pre-commit:**
  ```bash
  uv run pre-commit install
  ```

---

## 2. Rust Workspace (`crates/`)

The core software factory is structured into four crates:
- `crates/pa-core`: Core shared libraries, backends (Tart, Incus), Git Vault, and sandboxes.
- `crates/pa-cli`: Host developer binary (`pa`).
- `crates/pa-agentd`: Static guest VM control daemon.
- `crates/pa-landlock`: Native Linux Landlock ABI v4+ sandbox restrictor.

### Building & Testing Rust

```bash
# Compile all crates in debug mode
cargo build --workspace

# Compile all crates in release mode
cargo build --workspace --release

# Run the complete Rust test suite
cargo test --workspace

# Check formatting
cargo fmt --all -- --check

# Run Clippy lints
cargo clippy --workspace --all-targets -- -D warnings
```

---

## 3. Proxy Addons (`coding-agent-proxy/`)

The egress proxy utilizes `mitmproxy` addons to perform multi-agent port isolation, hostname filtering, and secret injection.

### Testing & Linting Proxy Addons

```bash
# Run pytest for all proxy addons
uv run pytest coding-agent-proxy/addons

# Format and lint Python code
uv run ruff check --fix
uv run ruff format

# Typecheck with strict Mypy
uv run mypy
```

---

## 4. Documentation & Website (`docs/`)

The documentation site is built using [Zensical](https://github.com/zensical/zensical) (Python-Markdown).

### Indentation Rules (`AGENTS.md`)
- Python-Markdown requires **4-space indentation** for nested list items. Multiples of 4 spaces must be used for all subsequent levels.
- Format Markdown files using the repository helper:
  ```bash
  uv run python3 scripts/format_markdown.py
  ```

### Linting & Previewing Docs

```bash
# Scan for Markdown syntax violations
uv run pymarkdown --config .pymarkdown.json scan

# Build the documentation site
uv run zensical build

# Live preview local doc server
uv run zensical serve
```

---

## 5. Full Pre-Commit Suite

Before submitting changes, run the complete pre-commit suite:

```bash
uv run pre-commit run --all-files
```
