# Releases & Versioning

Releases for PA-Container 2.0 are published as signed Git tags (`v*`) on the `main` branch. GitHub Actions automatically validates versions, runs the Rust workspace test suite, and creates GitHub releases with release notes extracted directly from [CHANGELOG.md](https://github.com/mikkovihonen/pa-container/blob/main/CHANGELOG.md).

---

## 1. Development Model: Trunk-Based Development

Development proceeds on short-lived branches off `main`. Changes land via pull requests.

```bash
git checkout -b feat/agent-cgroup-limits main
# ... edit, commit ...
git push origin feat/agent-cgroup-limits
# Open PR. CI runs Rust formatting, Clippy, cargo test, and proxy suites.
# Squash-merge to main.
```

### Branch Naming Conventions

| Prefix | Usage | Example |
| :--- | :--- | :--- |
| `feat/` | New features or capabilities | `feat/seatbelt-profiles` |
| `fix/` | Bug fixes and security patches | `fix/proxy-port-attribution` |
| `chore/` | Tooling, dependencies, and docs | `chore/bump-landlock` |

---

## 2. Semantic Versioning

PA-Container adheres to [Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html):

$$\text{v}\textit{MAJOR}.\textit{MINOR}.\textit{PATCH}$$

- **MAJOR:** Breaking changes in CLI arguments, `factory.toml` schemas, or sandbox boundaries.
- **MINOR:** New backward-compatible features, capability packs, or hypervisor backends.
- **PATCH:** Backward-compatible bug fixes and performance improvements.

### Authoritative Version Sources

The release version must stay synchronized across three locations:

| Source | File Path | Field / Notation |
| :--- | :--- | :--- |
| **Cargo Workspace** | `Cargo.toml` | `[workspace.package] version = "2.0.0"` |
| **Python Metadata** | `pyproject.toml` | `[project] version = "2.0.0"` |
| **Git Tag** | Git reference | `v2.0.0` |

Version consistency is verified locally and in CI using the version gate script:

```bash
pa version check
```

---

## 3. Creating a Release

To cut a new release:

1. **Verify Clean CI on `main`:**
    - Ensure all jobs in `.github/workflows/ci.yml` pass on `main`.
2. **Update `CHANGELOG.md`:**
    - Move `[Unreleased]` changes into a new version section: `## [2.0.0] - YYYY-MM-DD`.
3. **Bump Workspace Versions:**
    - Update `version` in `Cargo.toml` (`[workspace.package]`).
    - Update `version` in `pyproject.toml` (`[project]`).
    - Run `cargo check` and `uv lock` to update lockfiles.
4. **Run Pre-Flight Validation:**
    ```bash
    pa version check --target 2.0.0
    uv run pre-commit run --all-files
    ```
5. **Commit, Tag, and Push:**
    ```bash
    git add Cargo.toml Cargo.lock pyproject.toml uv.lock CHANGELOG.md
    git commit -m "chore: prepare release v2.0.0"
    git push origin main

    git tag -a v2.0.0 -m "Release v2.0.0"
    git push origin v2.0.0
    ```

---

## 4. Automated CI Release Job

When a tag matching `refs/tags/v*` is pushed:

- **`rust-check`**: Validates `cargo fmt`, `cargo clippy`, and runs `cargo test --workspace`.
- **`proxy-and-docs`**: Runs proxy addon tests, typechecks, markdown checks, and builds the documentation site.
- **`release`**: Extracts the matching version section from `CHANGELOG.md` and creates the official GitHub Release with artifacts.
