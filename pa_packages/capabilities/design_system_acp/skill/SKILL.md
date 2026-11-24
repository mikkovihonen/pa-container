---
name: design_system_acp
description: Read-only Design System context from W3C DTCG tokens, component contracts, deprecation registries, and live Penpot visual board specs.
---

# Design System Context Skill

This skill provides read-only design system discovery tools powered by the `design_system_acp` Model Context Protocol (MCP) server. Agents use these tools to inspect design tokens, validate component contracts, and query visual board specifications before generating UI code.

## Available Tools

- `design.search_tokens(query: str = "", platform: str = "web", category: str = None)`
    - Searches and flattens tokens defined in W3C DTCG `design/tokens/tokens.json`.
    - Generates ready-to-use code snippets for the target platform:
        - `web`: CSS custom properties (e.g. `--color-brand-primary: #2563eb;`).
        - `ios`: Swift declarations (e.g. `let ColorBrandPrimary = "#2563eb"`).
        - `android`: Kotlin declarations (e.g. `val ColorBrandPrimary = "#2563eb"`).
    - Usage: Call whenever styling UI components to ensure color, spacing, and typography conform to design tokens.
- `design.get_component_contract(component: str)`
    - Reads component contracts from `design/contracts/<component>.toml`.
    - Returns component name, accessibility targets (WCAG / VoiceOver / TalkBack), platform component source paths, catalog entries, and validates declared token dependencies.
    - Usage: Call before implementing or refactoring UI components to verify contract requirements.
- `design.list_deprecated()`
    - Scans tokens and component contracts for deprecation notices, recommended replacements, and sunset versions.
    - Usage: Call during refactoring or lint audits to prevent introducing obsolete design primitives.
- `design.get_board_spec(board_id: str = None, file_id: str = None)`
    - Inspects live visual design boards via Penpot or Figma HTTP APIs.
    - Operates in `git_only` mode if no remote design provider is configured, returning local contract references.
    - Usage: Call to inspect visual frame layouts or export design specs from Penpot.

## Invocation Guidelines

- **Read-Only Invariant:** These tools never write or modify tokens, contracts, or remote design boards.
- **Contract First:** Always check `design.get_component_contract` before writing component source code.
