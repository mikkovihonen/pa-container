---
name: git
description: "Git version control, branching, atomic commits, Git LFS asset tracking, and GitHub CLI (gh) operations."
---

# Git Version Control (`git`)

Provides core Git version control, Git LFS large asset tracking, and GitHub CLI (`gh`) integration.

## Tool Overview

| Task | Tool | Primary Command |
|---|---|---|
| Repository status and dirty tree inspection | `git status` | `git status --short` |
| Atomic commit creation | `git commit` | `git commit -m "feat: description"` |
| Worktree and branch management | `git branch` | `git checkout -b feature/branch` |
| GitHub PR and issue management | `gh` | `gh pr create --title "..." --body "..."` |
| Large file storage tracking | `git lfs` | `git lfs track "*.bin"` |

## Common Recipes

### Atomic Commit with Clean Message

```sh
git add path/to/file.ext
git commit -m "feat(module): implement feature logic"
```

### GitHub Pull Request Creation

```sh
gh pr create --title "feat: implement feature" --body "Detailed summary of changes"
```

### Git LFS Tracking

```sh
git lfs install
git lfs track "*.weights" "*.bin"
git add .gitattributes
```

## Guidelines
- **Zero interactive prompts**: `GIT_TERMINAL_PROMPT=0` is set to ensure automated agent workflows fail safely on missing credentials rather than hanging.
- **Atomic changes**: Always review staged diffs with `git diff --cached` before committing.
