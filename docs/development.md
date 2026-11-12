# Development

The host-side Python (`pa_core/`) is managed with [uv](https://docs.astral.sh/uv/). Dependencies are declared in `pyproject.toml` and pinned in `uv.lock`.

```bash
# Provision / update the environment (runtime deps + the default `dev` group)
uv sync

# Run the project's test suite (pa_core/tests and pa_packages)
uv run pytest

# Lint / format / type check
uv run ruff check pa_core pa_packages
uv run ruff format pa_core pa_packages
uv run mypy

# Run the mitmproxy proxy-addon tests (heavy `mitmproxy` dep — opt-in group)
uv run --group proxy pytest coding-agent-proxy/addons
```

The Python sources run directly from `pa_core/`. The `pa` executable in the repository
root wraps `uv run --project <repo>`, preserving the caller's working directory
as the project workspace. In addition, the package provides a standard entry point
`pa = "cli:main"` in `pyproject.toml`.

<a name="coverage"></a>
## Coverage

CI enforces test coverage (minimum 90%). The system measures coverage with `pytest-cov`. The CI auto-commits a badge SVG to `docs/assets/coverage.svg` on every push to `main`.

Run locally:

```bash
uv run pytest --cov --cov-report=term-missing
```

<a name="schema-validation"></a>
## Schema validation

The system validates per-project configuration (`.pa-container/config.yaml`) at launch
against the pa-container version and the expected schema. The validation checks:

1. **Schema version** — The `schema_version` field in the config matches the
   app version (from the latest git tag). Bump this field in the templates
   (`coding-agent/default/project/config.yaml` and `coding-agent/default/global/config.yaml`) whenever you change the schema.
2. **Required fields** — All fields defined in the schema must be present with
   the correct types.

Validation failure makes the launch exit with a clear error message. The message lists the
issues and suggests the fix (delete `.pa-container` and re-run).

The validation logic lives in `pa_core/config_schema.py` and is tested in
`pa_core/tests/test_config_schema.py`.
