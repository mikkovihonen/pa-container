---
name: upgrade-toolchains
description: Audits and upgrades tools and runtimes in Agent Capability Packages (Go, Rust, Node, Python, mold, git, ripgrep, AST/LSP tools, vector DBs) to their latest upstream releases. Use when the user asks to "check for tool updates", "upgrade toolchains", "update ripgrep/mold/git", or "upgrade all tools".
---

# Upgrade Toolchains and Agent Capability Packages

## When to Use

Use this skill whenever the user asks to inspect, audit, or upgrade any of the tools or runtimes in `packages/`. Examples:
- "Check for toolchain updates"
- "Are any of our packages outdated?"
- "Upgrade ripgrep to the latest version"
- "Upgrade mold and git"
- "Upgrade all LSPs"
- "Upgrade all tools"

## Available Tool Groups

- **`compilers`**: `mold`, `go`, `rust`
- **`search`**: `ripgrep`, `fd`, `ast-grep`, `tree-sitter-cli`, `colgrep`
- **`vector`**: `qdrant`, `sqlite-vec`
- **`lsp`**: `rust-analyzer`, `gopls`, `clangd`, `zls`
- **`vcs`**: `git`, `ruby`, `gh`, `glab`, `tea`, `az`, `cafe`
- **`tools`**: `t3`, `chromium`
- **`agents`**: `pi`, `opencode`, `claude-code`, `antigravity`, `antigravity-acp`
- **`core`**: Core runtime dependencies (`python`, `go`, `rust`, `node`, `podman`, `netavark`, `aardvark-dns`, `uv`, `podman-compose`, `python-dotenv`, `pyyaml`)

## Workflows

### 1. Audit Available Upgrades (Read-Only)

To audit all 30+ packages and print an aligned comparison table showing Current vs. Upstream releases:

```bash
uv run python3 .pi/skills/upgrade-toolchains/scripts/check_upgrades.py --check
```

Present the table to the user and highlight which tools have available upgrades.

### 2. Upgrading a Specific Tool

To upgrade a single package (e.g. `mold`):

```bash
uv run python3 .pi/skills/upgrade-toolchains/scripts/check_upgrades.py --upgrade mold --verify
```

The script will:
- Query upstream git tags/manifests to resolve the latest version and peeled commit hash.
- Update the corresponding version and checksums in `packages/<tool>/package.yaml`.
- Execute `src/tests/test_packages.py` and `src/tests/test_build.py` to guarantee all package contracts are preserved.

### 3. Upgrading a Functional Group

To upgrade an entire domain together (e.g. all LSPs or search tools):

```bash
uv run python3 .pi/skills/upgrade-toolchains/scripts/check_upgrades.py --upgrade-group lsp --verify
```

### 4. Upgrading All Outdated Tools

```bash
uv run python3 .pi/skills/upgrade-toolchains/scripts/check_upgrades.py --upgrade all --verify
```

### 5. Verification & Pre-Commit Checks

After applying upgrades:
1. Verify package validation tests pass:
    ```bash
    uv run pytest src/tests/test_packages.py src/tests/test_build.py -k TestPackageManifestsAreValid
    ```
2. Verify package container build (e.g. for the upgraded tool):
    ```bash
    pa build --packages <tool>
    ```
3. Run all workspace pre-commit checks:
    ```bash
    uv run pre-commit run --all-files
    ```
4. Commit the changes:
    ```bash
    git add packages/<tool>/package.yaml
    git commit -m "chore(packages): upgrade <tool> to <new_version>"
    ```

## Error Handling & Safety

- **Manifest validation failure**: If `test_packages.py` fails after an upgrade, verify the `package.yaml` syntax matches schema.
- **Rollback**: To discard changes before committing:
    ```bash
    git checkout packages/<tool>/package.yaml
    ```

