# Developer Tools (`developer-tools`)

Provides command running and developer workflow utilities.

## Constituent Tools
- `just`: A handy way to save and run project-specific commands, alternative to `make` without make's idiosyncrasies.

## Usage Guidelines
- **Recipe Execution**:
    - List available recipes: `just --list`
    - Run default recipe: `just`
    - Run specific recipe with arguments: `just test --all`
    - Dry run recipe without executing: `just --dry-run deploy`
- **Recipe Inspection**:
    - Show recipe definition: `just --show build`
    - Evaluate variables: `just --evaluate`
