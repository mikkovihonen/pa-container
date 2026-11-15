# Feature Implementation Workflow

PA-Container 2.0 introduces an **Agentic Software Development Lifecycle (ADLC)** centered around **Spec-Driven Development (SDD)**, strict **Anti-Tamper Red-Green TDD**, and **Two-Stage Human-in-the-Loop Gating**.

---

## 1. Overview & Tenets

Autonomous coding agents excel at speed but struggle with ambiguous requirements or unconstrained scope. The PA-Container feature workflow enforces five foundational principles:

1. **Spec-Driven Planning:** Features are never implemented directly from rough prompts. An interactive interview with an in-guest **Architect Agent (UID 2001)** produces machine-readable contracts before code generation starts.
2. **Tenant Role Specialization:** Execution progresses across isolated POSIX UIDs:
    - **Architect (UID 2001):** Interactive requirements capture and vertical task slicing.
    - **Test Engineer (UID 2002):** Red-phase test authoring and failure verification.
    - **Implementer (UID 2003):** Green-phase minimal implementation.
    - **Verifier (UID 2004):** Static analysis, mutation tests, and multimodal visual checks.
3. **Assertion-Locked TDD:** During the green phase, test directories (`tests/`, `*_test.rs`, `test_*.py`) are locked **read-only** by the OS kernel sandbox (Seatbelt / Landlock), preventing agents from weakening assertions or faking test passes.
4. **Multimodal Visual Verification:** UI and mobile features are validated against target displays via **Virtual Desktop** (`agent-desktop` under Wayland/Quartz) and **iOS Simulator** (`pa-ios`), capturing visual evidence in `.pa/features/<slug>/evidence/`.
5. **Two-Stage Human Gating:** Humans sign off on the specification upfront (**Gate 1**), and review the isolated worktree diffs and visual artifacts (**Gate 2**) before merging.

---

## 2. The Feature CLI (`pa feature`)

### 2.1 Interactive Planning (Gate 1)

Initiate an interactive interview session with the Architect Agent:

```bash
pa feature plan <feature-slug>
```

In interactive mode, the Architect inquires about:
- **Feature Title & Intent:** Business goal and problem statement.
- **User Stories:** Structured role/goal/benefit definitions.
- **Non-Goals & Constraints:** Explicit architectural boundaries.
- **Acceptance Criteria:** Verifiable conditions for completion.
- **Test Matrix:** Unit, integration, and visual test expectations.

This generates version-controlled contract files in `.pa/features/<slug>/`:
- `spec.md`: User stories, constraints, and acceptance criteria.
- `tasks.md`: Ordered vertical tracer-bullet task slices.
- `test_plan.md`: Test scenario definitions and expected outcomes.

Upon generation, select `[A]` to approve the specification (Gate 1 sign-off).

### 2.2 Inspecting Feature Status

Query the status and verification artifacts of any feature:

```bash
# List all repository features
pa feature status

# Detailed inspection of a specific feature
pa feature status <feature-slug>

# JSON output for CI pipelines
pa feature status <feature-slug> --json
```

### 2.3 Running the Multi-Agent Pipeline

Execute the autonomous implementation stages:

```bash
# Run all stages sequentially (Red -> Green -> Verify)
pa feature run <feature-slug>

# Run a specific stage
pa feature run <feature-slug> --stage red
pa feature run <feature-slug> --stage green
pa feature run <feature-slug> --stage verify
```

### 2.4 Reviewing and Merging (Gate 2)

Inspect agent modifications in an isolated host review worktree:

```bash
# View review worktree location and verification evidence
pa feature review <feature-slug>

# Open review worktree directly in your editor
pa feature review <feature-slug> --open --ide code

# Submit feedback for an iterative revision cycle
pa feature review <feature-slug> --feedback "Adjust padding and re-run visual check"

# Approve and merge the verified feature into target branch
pa feature review <feature-slug> --approve
```
