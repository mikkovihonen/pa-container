## Optional Feature: C/C++ Language Server (`clangd`)

Provides index-based code completion, navigation, and static analysis for C and C++ projects.

### Capabilities
- Fast AST-level completion and macro expansions.
- Cross-translation-unit references and definitions with `compile_commands.json`.
- Clang-tidy integration for inline lint warnings and fixes.

### Usage
- Binary: `/usr/local/bin/clangd`
- Check version: `clangd --version`
- Recommended flags: `clangd --background-index --clang-tidy`
