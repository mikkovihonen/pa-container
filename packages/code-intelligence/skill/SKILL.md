---
name: code-intelligence
description: Polyglot codebase search, AST structural matching, syntax parsing, and context packing.
---

# Code Intelligence Capability

This package provides a unified suite of tools for codebase exploration, structural pattern matching, syntax tree analysis, and context packaging.

## Tooling Overview

| Tool | Binary | Primary Use Case |
| :--- | :--- | :--- |
| **ripgrep** | `rg` | Ultra-fast line-oriented literal and regex text search across files. |
| **fd** | `fd` | Fast, intuitive file and directory hierarchy discovery (replaces `find`). |
| **ast-grep** | `ast-grep` / `sg` | Syntax-aware structural pattern matching and rule-based code rewriting across 20+ languages. |
| **tree-sitter** | `tree-sitter` | Concrete syntax tree parser and grammar validator. |
| **repomix** | `repomix` | Pack repositories and directory subsets into structured, token-counted context for LLMs. |
| **tokencount** | `tokencount` | Fast token usage estimation for files and subtrees. |
| **colgrep** | `colgrep` | Colorized search visualizer. |

---

## Search Triage Heuristics

When investigating codebases, choose the tool that fits the task:

1. **Locating files or directories by name or glob**:
    - Use `fd`. Never use `find`.
    - Examples:
        - `fd -e py` (find all Python files)
        - `fd "config" src/` (find files with "config" in the name under `src/`)
        - `fd -H` (include hidden files)
2. **Finding literal strings, error messages, identifiers, or regexes**:
    - Use `rg`.
    - Examples:
        - `rg "def parse_manifest"` (find exact function definition)
        - `rg -t rust "Clone"` (search only Rust files)
        - `rg -l "deprecated"` (list only file paths containing the match)
3. **Finding syntactic patterns or refactoring code across lines/languages**:
    - Use `ast-grep` (`sg`).
    - Unlike regex, `ast-grep` parses code into an AST and matches structural patterns regardless of whitespace, formatting, or comments.
    - Examples:
        - `sg -p 'console.log($$$)'` (find all console.log calls with any arguments)
        - `sg -p 'def $NAME($$$): pass'` (find all stub functions in Python)
        - `sg -p 'expect($A).toEqual($B)' -r 'expect($A).toStrictEqual($B)'` (rewrite pattern across codebase)
4. **Validating grammar and inspecting syntax trees**:
    - Use `tree-sitter parse <file>`.
5. **Packing codebase context or measuring token usage**:
    - Use `repomix` to bundle relevant files into a clean XML/Markdown context prompt:
        - `repomix --include "src/packages/**"`
    - Use `tokencount` to check token budgets:
        - `tokencount src/build.py`
