# Configuration Reference: PA-Container 2.0

PA-Container 2.0 uses declarative TOML configurations for both factory VM orchestration (`factory.toml`) and modular capability packs (`capability.toml`).

---

## 1. Factory Configuration (`factory.toml`)

The root `factory.toml` file declares the multi-agent topology, hypervisor backend settings, and network proxy rules for the software factory.

### Schema Version 2.0 Specification

```toml
schema_version = "2.0"

[factory]
name = "pa-factory"
description = "Software Factory VM for multi-agent workflows"

[compute]
# Hypervisor backend: "auto", "macos-tart", "linux-incus", or "linux-cloud"
backend = "auto"
cpus = 8
memory_mb = 16384
gpu = "optional"

[compute.metal]
# Explicit opt-in for macOS Apple Silicon paravirtualized Metal capabilities
enabled = true
# Host preference lifecycle: "ephemeral" (default, reverts on factory down), "persistent", or "none"
host_mode = "ephemeral"
# Target Apple GPU family ceiling (1001-1999, default 1009 = Apple Family 9 / M3/M4)
apple_family_max = 1009
# Threadgroup memory floor in bytes (default 65536 = 64 KiB)
max_threadgroup_memory = 65536

[compute.llama_server]
# Native host LLM inference server supervision (Metal / CUDA / ROCm)
enabled = false
managed_lifecycle = true
# binary_path = "/usr/local/bin/llama-server"
# model_path = "models/qwen2.5-coder-7b.gguf"
host = "127.0.0.1"
port = 8081
ctx_size = 32768
gpu_layers = -1
extra_args = ["--metrics"]
startup_timeout_sec = 120
on_missing_binary = "skip"

[proxy]
base_proxy_port = 8081
base_transparent_port = 8091
dns_port = 5353
default_allowlist = ["github.com", "pypi.org", "registry.npmjs.org"]

[git]
default_branch = "main"
vault_path = "/var/pa-vault"
branch_pattern = "refs/heads/pa/{agent_id}/*"

[telemetry.otlp]
enabled = true
# Provider: "phoenix", "langfuse", "otlp_generic", or "none"
provider = "phoenix"
endpoint = "http://127.0.0.1:4318"
ui_endpoint = "http://127.0.0.1:6006"
service_name = "pa-factory"
sample_rate = 1.0
scrub_secrets = true
export_prompts = true

[storage]
# Provider: "sqlite", "postgres", or "clickhouse"
provider = "sqlite"
path = ".pa/factory.db"

[traceability]
# Engine: "openfasttrace", "strictdoc", "custom_cmd", or "none"
engine = "openfasttrace"
spec_dir = "docs/specs"
min_coverage_pct = 95.0
enforce_test_linkage = true
junit_report_paths = [".pa/reports/junit.xml"]
coverage_report_path = ".pa/reports/lcov.info"
require_test_execution = false
min_line_coverage_pct = 80.0
on_missing_tool = "skip"

[design_system]
enabled = true
# Provider: "git_only", "penpot", "figma", or "none"
provider = "git_only"
tokens_path = "design/tokens/tokens.json"
contracts_path = "design/contracts"
platforms = ["web", "ios", "android"]
on_missing_platform = "skip"

[design_system.drift]
enabled = true
engine = "native"
flag_new_primitives = true
on_raw_primitive = "warn"
on_new_primitive = "needs_design_review"

[design_system.ios]
enabled = true
visual_diff_tool = "swift_snapshot"
max_visual_diff_pct = 0.05
on_missing_platform = "skip"

[design_system.android]
enabled = true
visual_diff_tool = "paparazzi"
max_visual_diff_pct = 0.05
on_missing_platform = "skip"

[governance]
enabled = true
max_wip_prs = 5
slo_defense_error_budget_min = 0.05
budget_usd_per_kr = 100.0
fallback_model = "qwen2.5-coder-7b-instruct"
fallback_base_url = "http://127.0.0.1:11434/v1"

[governance.self_optimization]
enabled = true
window_days = 30
min_failure_class_count = 2
cfr_spike_threshold = 0.15
min_rolling_fpy = 0.70
min_eval_score = 0.75
kr_budget_warn_pct = 0.85
cooldown_hours = 24
auto_enqueue_diagnostician = true
auto_enqueue_okr_analyst = true

[[quality_gates]]
name = "db-lock-gate"
command = "cargo test -p pa-core test_db"
trigger = "failure_class:db_lock"
enabled = false
description = "Dormant gate automatically activated by pa telemetry harden when db_lock recurs"

[roles.spec_author]
description = "Drafts and refines functional specs and OKR links"
capabilities = ["traceability:read", "traceability:write"]

[roles.design_engineer]
description = "Authors and validates cross-platform design tokens and contracts"
capabilities = ["design_system:read", "design_system:write"]

[[agents]]
id = "agent1"
uid = 2001
driver = "pi"
role = "spec_author"
capabilities = ["git", "source-control", "image-tools"]
allowlist = ["api.openai.com", "generativelanguage.googleapis.com"]
tokens = ["OPENAI_API_KEY", "GEMINI_API_KEY"]

[[agents]]
id = "agent2"
uid = 2002
driver = "claude"
capabilities = ["git", "source-control", "document-tools"]
allowlist = ["api.anthropic.com"]
tokens = ["ANTHROPIC_API_KEY"]
```

### Configuration Sections

#### `[factory]`
- **`name`**: Descriptive label for the software factory.
- **`description`**: Optional textual description.

#### `[compute]`
- **`backend`**: Hypervisor orchestration engine. Defaults to `"auto"`, which detects Tart on macOS Apple Silicon and Incus on Linux.
- **`cpus`**: Number of virtual CPU cores allocated to the factory VM.
- **`memory_mb`**: RAM allocated in megabytes (minimum 4096 recommended).
- **`gpu`**: GPU allocation policy (`"optional"`, `"required"`, or `"disabled"`).

#### `[compute.metal]`
- **`enabled`**: Explicit opt-in boolean (defaults to `false`). When `false`, zero host preferences are touched and guest processes run stock virtual graphics.
- **`host_mode`**: Host hypervisor preference lifecycle:
    - `"ephemeral"` *(Default)*: Automatically sets `defaults write com.apple.gpusw.ParavirtualizedGraphics ForceUnrestrictedDeviceFeatureLevel -bool true` on the host prior to Tart execution, and cleanly deletes it upon factory teardown (`pa factory down`). Leaves zero persistent host changes.
    - `"persistent"`: Sets the host preference permanently.
    - `"none"`: Never modifies host settings (assumes external out-of-band management).
- **`apple_family_max`**: Maximum Apple GPU feature tier to expose via the interposer shim (defaults to `1009` for Apple Family 9 / M3/M4).
- **`max_threadgroup_memory`**: Memory ceiling in bytes (defaults to `65536` for 64 KiB, overcoming stock 32 KiB restriction).

#### `[compute.llama_server]`
- **`enabled`**: Master toggle for local host LLM inference server supervision (defaults to `false`).
- **`managed_lifecycle`**: When `true` (default), `pa factory up` spawns and health-checks `llama-server` on the host, and `pa factory down` releases/terminates it. When `false`, verifies external availability without process management.
- **`binary_path`**: Optional explicit path to `llama-server` binary. If omitted, searches `$PATH` and `~/.local/share/pa-container/bin/`.
- **`model_path`**: Path to the GGUF model file loaded into memory.
- **`host`**: Host interface to bind (defaults to `"127.0.0.1"`).
- **`port`**: Port number for `llama-server` (defaults to `8081` to avoid colliding with `coding-agent-proxy` at `8080`).
- **`ctx_size`**: Context window size in tokens (defaults to `32768`).
- **`gpu_layers`**: Number of layers offloaded to host GPU (`-1` or `"all"` for complete offload, integer for specific layer count).
- **`extra_args`**: Additional flags passed directly to `llama-server` (e.g. `["--metrics", "--threads", "8"]`).
- **`startup_timeout_sec`**: Health polling timeout in seconds while model loads (`503` to `200 OK`, defaults to `120`).
- **`on_missing_binary`**: Failure policy if `llama-server` binary cannot be resolved:
    - `"skip"` *(Default)*: Emits a warning and proceeds without local inference.
    - `"block"`: Aborts `pa factory up` with an error.

#### `[proxy]`
- **`base_proxy_port`**: Starting port number for dedicated agent HTTP/HTTPS proxy listeners (defaults to `8081`).
- **`base_transparent_port`**: Starting port number for transparent egress redirection (defaults to `8091`).
- **`dns_port`**: Internal DNS resolver port (defaults to `5353`).
- **`default_allowlist`**: Hostnames universally reachable across all agents.

#### `[telemetry.otlp]`
- **`enabled`**: Master toggle for OpenTelemetry span export.
- **`provider`**: Active OTLP trace backend:
    - `"phoenix"` *(Default)*: Arize Phoenix tracing endpoint.
    - `"langfuse"`: Langfuse telemetry collector.
    - `"otlp_generic"`: Generic OpenTelemetry Collector HTTP endpoint.
    - `"none"`: Disables external telemetry; records local JSONL flow logs only.
- **`endpoint`**: HTTP endpoint for OTLP trace exports (defaults to `http://127.0.0.1:4318`).
- **`ui_endpoint`**: Optional URL opened by `pa telemetry ui` (e.g. `http://127.0.0.1:6006`).
- **`service_name`**: OpenTelemetry service name stamped on emitted spans (defaults to `pa-factory`).
- **`sample_rate`**: Span sampling ratio from `0.0` to `1.0` (defaults to `1.0`).
- **`scrub_secrets`**: Automatically redacts API keys, Bearer tokens, and passwords from span payloads.
- **`export_prompts`**: Whether sanitized LLM prompt and completion contents are exported in spans.

#### `[storage]`
- **`provider`**: Analytical database engine (`"sqlite"`, `"postgres"`, or `"clickhouse"`).
- **`path`**: Local SQLite database path (defaults to `.pa/factory.db`) or cloud connection URI.

#### `[traceability]`
- **`engine`**: Active specification scanner:
    - `"openfasttrace"` *(Default)*: Embedded scanner for `req~`, `impl~`, `utest~`, and `vtest~` tags.
    - `"strictdoc"`: StrictDoc requirements format adapter (`.sdoc` and `@relation(...)`).
    - `"custom_cmd"`: Invokes a custom external verification command.
    - `"none"`: Disables requirement traceability checks.
- **`spec_dir`**: Directory where specification documents reside (defaults to `docs/specs`).
- **`min_coverage_pct`**: Minimum required implementation and test coverage threshold (defaults to `95.0`).
- **`enforce_test_linkage`**: When `true`, every requirement must have linked test items (defaults to `true`).
- **`junit_report_paths`**: List of JUnit XML test report paths checked for execution verification (defaults to `[".pa/reports/junit.xml"]`).
- **`coverage_report_path`**: Path to an LCOV (`lcov.info`) or `gcov`/`llvm-cov` JSON report for line coverage measurement.
- **`require_test_execution`**: When `true`, requires that linked tests actually executed and passed in the JUnit XML report.
- **`min_line_coverage_pct`**: Optional minimum line coverage threshold for linked implementation files (0.0 to 100.0).
- **`on_missing_tool`**: Fallback policy when optional external tools (like `strictdoc` CLI) are not installed:
    - `"skip"` *(Default)*: Warns and continues with native pure-Rust analysis.
    - `"block"`: Hard-fails the gate.

#### `[design_system]`
- **`enabled`**: Master toggle for cross-platform design system contract verification.
- **`provider`**: Design token source:
    - `"git_only"` *(Default)*: Reads local W3C DTCG tokens and component contracts directly from Git.
    - `"penpot"`: Integrates with self-hosted or SaaS Penpot instances.
    - `"figma"`: Integrates with Figma REST APIs.
    - `"none"`: Disables design system verification.
- **`tokens_path`**: Path to W3C DTCG token catalog (defaults to `design/tokens/tokens.json`).
- **`contracts_path`**: Path to component contract definitions (defaults to `design/contracts`).
- **`platforms`**: Target platforms to verify (`["web"]`, `["web", "ios"]`, `["web", "ios", "android"]`). Defaults to `["web"]`.
- **`on_missing_platform`**: Behavior when a declared platform's host toolchain (`simctl`, `adb`) is missing:
    - `"fail"` *(Default for declared platforms)*: Hard-fails the gate with diagnostic instructions.
    - `"warn"`: Emits a structured warning and continues.
    - `"skip"`: Skips testing the missing platform without failing.

#### `[design_system.drift]`
- **`enabled`**: Enables AST component drift and raw primitive detection (defaults to `true`).
- **`engine`**: Drift analysis engine (`"native"` [default], `"external"`, `"hybrid"`, `"none"`).
- **`flag_new_primitives`**: When `true`, detects newly exported UI components outside contracts catalog (defaults to `true`).
- **`on_raw_primitive`**: Action when raw primitive (`<button>`, SwiftUI `Button`, Compose `Button`) is detected when an approved contract exists:
    - `"warn"` *(Default)*: Emits a lint warning.
    - `"block"`: Fails the gate.
- **`on_new_primitive`**: Action when an unregistered exported UI component is detected:
    - `"needs_design_review"` *(Default)*: Passes the gate, records `needs_design_review = true`, and stamps `X-PA-Design-Gate: needs-design-review`.
    - `"warn"`: Emits a warning and passes.
    - `"block"`: Fails the gate.
- **`linter_command`**: Optional external linter delegate command (e.g. `"npx eslint --format json"`).
- **`ignore_paths`**: Glob patterns excluded from drift scanning (defaults to `["**/tests/**", "**/*.test.*", "**/*.spec.*", "design/**"]`).

#### `[design_system.ios]`
- **`enabled`**: Enables native iOS SwiftUI and preview verification (defaults to `true`).
- **`paths`**: File globs triggering iOS checks (defaults to `["ios/**", "Sources/**", "**/*.swift"]`).
- **`runner`**: iOS simulator test execution runner (defaults to `"ios_runnerd"`).
- **`a11y_engine`**: Accessibility audit engine (defaults to `"xctest_a11y"`).
- **`a11y_command`**: Optional command to execute XCTest accessibility audits (`performAccessibilityAudit()`).
- **`visual_diff_tool`**: Visual regression diff tool (`"swift_snapshot"`, `"simctl_diff"`, `"custom_cmd"`, `"none"`).
- **`baseline_dir`**: Directory containing baseline reference screenshots (defaults to `"design/baselines/ios"`).
- **`max_visual_diff_pct`**: Maximum tolerated visual diff percentage (defaults to `0.05`).
- **`on_missing_platform`**: Behavior when `xcrun simctl` / Xcode CLI is missing (`"skip"` [default] or `"block"`).

#### `[design_system.android]`
- **`enabled`**: Enables native Android Jetpack Compose verification (defaults to `true`).
- **`paths`**: File globs triggering Android checks (defaults to `["android/**", "app/**", "**/*.kt"]`).
- **`runner`**: Android verification runner (defaults to `"paparazzi"`).
- **`a11y_engine`**: Android accessibility engine (defaults to `"espresso_a11y"`).
- **`a11y_command`**: Optional command to execute Android accessibility checks.
- **`visual_diff_tool`**: Visual regression tool (`"paparazzi"`, `"roborazzi"`, `"adb_screencap"`, `"custom_cmd"`, `"none"`).
- **`baseline_dir`**: Directory containing baseline reference screenshots (defaults to `"design/baselines/android"`).
- **`max_visual_diff_pct`**: Maximum tolerated visual diff percentage (defaults to `0.05`).
- **`adb_host`**: ADB server endpoint for live emulator commands (defaults to `"host.containers.internal:5037"`).
- **`on_missing_platform`**: Behavior when Android SDK / ADB / Gradle is missing (`"skip"` [default] or `"block"`).

#### `[governance]`
- **`enabled`**: Enables closed-loop governance gating before task dispatch.
- **`max_wip_prs`**: Maximum permitted active feature branches / unmerged PRs (e.g. `5`).
- **`slo_defense_error_budget_min`**: Minimum remaining service error budget before non-critical tasks are blocked (e.g. `0.05`).
- **`budget_usd_per_kr`**: Spending ceiling in USD per Key Result. When reached, task dispatch routes to local offline inference.
- **`fallback_model`**: Offline model name to use when throttled (e.g. `qwen2.5-coder-7b-instruct`).
- **`fallback_base_url`**: Offline API endpoint for throttled tasks (e.g. `http://127.0.0.1:11434/v1`).

#### `[governance.self_optimization]`
- **`enabled`**: Enables automated anomaly detection and self-optimization evaluation (defaults to `true`).
- **`window_days`**: Lookback analysis window in days for rolling metrics and recurring failure classes (defaults to `30`).
- **`min_failure_class_count`**: Minimum recurring occurrences within `window_days` before gate hardening or diagnostic dispatch triggers (defaults to `2`).
- **`cfr_spike_threshold`**: Change Failure Rate threshold above which an anomaly trigger fires (defaults to `0.15` or 15%).
- **`min_rolling_fpy`**: First Pass Yield floor below which an anomaly trigger fires (defaults to `0.70` or 70%).
- **`min_eval_score`**: LLM eval rubric mean score floor below which an anomaly trigger fires (defaults to `0.75`).
- **`kr_budget_warn_pct`**: Key Result budget consumption ratio at which an executive risk warning fires (defaults to `0.85` or 85%).
- **`cooldown_hours`**: Cooldown window in hours preventing duplicate events or tasks for the same fingerprint (defaults to `24`).
- **`auto_enqueue_diagnostician`**: Automatically enqueues `factory_diagnostician` upon unmatched failure classes or performance drops (defaults to `true`).
- **`auto_enqueue_okr_analyst`**: Automatically enqueues `okr_analyst` or generates executive briefs upon KR budget warnings (defaults to `true`).
- **`in_place_apply`**: Governs whether `pa telemetry harden --apply` directly modifies `factory.toml` in-place on the working branch (defaults to `true`).
- **`git_branch_prefix`**: Branch name prefix for autonomous diagnostic PR proposals (defaults to `"factory/harden"`).

#### `[[quality_gates]]`
- **`name`**: Identifier for the verification gate (e.g. `"db-lock-gate"`).
- **`command`**: Execution command for the gate test or check (e.g. `"cargo test -p pa-core test_db"`).
- **`trigger`**: Trigger activation condition (`"always"` or `"failure_class:<name>"`).
- **`enabled`**: Whether the gate is active or dormant (`true` or `false`).
- **`description`**: Human-readable documentation for the gate's intent.

#### `[routing.escalation]`
- **`enabled`**: Enables dynamic upward model tier escalation upon test or gate failures (defaults to `true`).
- **`chain`**: Ordered list of model tiers to escalate through (e.g. `["local", "frontier", "frontier+verifier"]`).
- **`max_retries_per_tier`**: Maximum retries on the current tier before escalating upward (defaults to `2`).
- **`escalate_on`**: Failure triggers that qualify for upward escalation (`["test_failure", "gate_failure", "eval_failure"]`).
- **`respect_kr_budget`**: Enforces Key Result budget guardrail, blocking paid frontier escalation when exhausted unless overridden with `--force`.

#### `[supervisor]`
- **`daemon`**: Runs host supervisor in background daemon mode with Unix socket IPC (defaults to `false`).
- **`max_concurrent_agents`**: Maximum parallel agent tasks and allocated sandbox slots (defaults to `4`).
- **`slot_uid_start`**: Starting guest POSIX UID allocated for concurrent sandboxes (defaults to `2001`).
- **`slot_proxy_port_start`**: Starting egress proxy listener port for concurrent sandboxes (defaults to `8081`).
- **`reallocate_roles`**: Specialized remediation roles dispatched when WIP limits are reached (e.g. `review_assist`, `verifier`, `traceability_auditor`, `design_steward`).

#### `[evals]`
- **`enabled`**: Enables automated LLM evals and rubrics evaluation (defaults to `false`).
- **`mode`**: Evaluation mode (`"cascade"` [default], `"system1"`, `"system2"`).
- **`rubrics_dir`**: Directory containing Git-versioned TOML rubrics (defaults to `docs/evals/rubrics`).
- **`min_pass_score`**: Minimum aggregate score required to pass quality gate (defaults to `0.80`).
- **`block_on_fail`**: Blocks feature verification and triggers escalation on eval failure (defaults to `true`).
- **`on_eval_unavailable`**: Behavior when judge endpoints are unreachable (`"skip"` [default] or `"block"`).
- **`escalate_to_system2_below_confidence`**: System 1 confidence threshold below which System 2 generative judge is invoked (defaults to `0.80`).
- **`escalate_on_fail_for_rationale`**: Automatically invokes System 2 generative judge on failing verdicts to generate remediation rationale (defaults to `true`).
- **`fence_untrusted_diffs`**: Encloses untrusted agent diffs in XML boundary delimiters with anti-injection instructions (defaults to `true`).
- **`enforce_distinct_model_family`**: Checks that judge model family is distinct from generator model family to mitigate self-evaluation bias (defaults to `true`).

#### `[evals.system1]`
- **`provider`**: System 1 decision model adapter (`"decision_http"`, `"local_decision"`, `"none"`).
- **`endpoint`**: HTTP endpoint accepting structured state and typed question checklists.
- **`model`**: Decision model name (e.g. `typesafe-jev-v1`).
- **`keyring_token`**: Optional secret token key resolved from host keyring or environment.

#### `[evals.system2]`
- **`provider`**: System 2 generative LLM judge (`"openai_compat"`, `"anthropic"`, `"gemini"`, `"llama_server"`, `"none"`).
- **`endpoint`**: Chat completions API endpoint (e.g. `http://127.0.0.1:8080/v1/chat/completions`).
- **`model`**: Generative judge model name (e.g. `qwen2.5-coder-32b`, `claude-3-5-sonnet`).
- **`temperature`**: Generation temperature (defaults strictly to `0.0` for determinism).
- **`keyring_token`**: Optional secret token key resolved from host keyring or environment.

#### `[roles.<name>]`
- **`description`**: Human-readable explanation of the role's responsibilities.
- **`capabilities`**: Granular capability permissions granted to the role (e.g. `traceability:read`, `design_system:write`).

#### `[[agents]]`
- **`id`**: Unique string identifier for the agent (e.g. `agent1`, `lead-architect`).
- **`uid`**: POSIX user identifier assigned inside the VM (must be $\ge 2001$).
- **`driver`**: Supported agent runner (`pi`, `claude`, `opencode`, `antigravity`).
- **`role`**: *(Optional)* Specialized agent role name declared under `[roles]` (e.g. `spec_author`, `design_engineer`).
- **`capabilities`**: List of capability packs mounted into the agent's environment.
- **`allowlist`**: Agent-specific destination domains permitted through the proxy.
- **`tokens`**: Environment variables subject to HMAC placeholder generation and dynamic proxy secret injection.

---

## 2. Capability Manifest (`capability.toml`)

Every directory under `pa_packages/capabilities/`, `pa_packages/toolchains/`, and `pa_packages/agents/` defines a self-contained capability manifest.

### Schema Version 1.0 Specification

```toml
schema_version = "1.0"

[capability]
name = "image-tools"
category = "media"
version = "1.0.0"
description = "Image processing capability: ImageMagick conversion, ExifTool metadata, WebP/JPEG/PNG utilities"
requires = []

[staging]
install_prefix = "/opt/pa/packs/image-tools"
bin_dirs = ["bin"]

[env]
MAGICK_MEMORY_LIMIT = "1GiB"

[proxy]
allowlist = ["api.stability.ai"]

[[proxy.tokens]]
env_var = "STABILITY_API_KEY"
allowed_hosts = ["api.stability.ai"]
```

### Manifest Fields

- **`[capability]`**:
    - **`name`**: Unique identifier of the pack.
    - **`category`**: Semantic classification (`media`, `devtools`, `cloud`, `browser`, `desktop`, etc.).
    - **`requires`**: Ordered list of prerequisite capability packs resolved topologically.
- **`[staging]`**:
    - **`install_prefix`**: Filesystem destination inside the VM.
    - **`bin_dirs`**: Subdirectories appended to the agent's `$PATH`.
    - **`fedora_packages`**: Native Fedora packages provisioned dynamically in guest Linux VMs via `dnf install -y`.
    - **`macos_brew_packages`**: Native Homebrew packages provisioned dynamically in guest macOS VMs via `brew install`.
- **`[entitlements]`**:
    - **`read_paths`**: Additional filesystem read paths granted in Seatbelt profiles or Bubblewrap mounts.
    - **`write_paths`**: Additional filesystem write paths granted in Seatbelt profiles or Bubblewrap mounts.
    - **`allow_gpu`**: Enables hardware compute access (Metal/CoreML IOKit on macOS, `/dev/dri` and compute nodes on Linux).
    - **`allow_network_bind`**: Local TCP ports the agent sandbox is permitted to bind.
- **`[env]`**:
    - Environment variables injected into the agent's sandboxed execution environment.
- **`[proxy]`**:
    - **`allowlist`**: Outbound hostnames permitted when this pack is attached to an agent.
    - **`[[proxy.tokens]]`**: Scopes token injection so secrets are only injected to authorized target hosts.
