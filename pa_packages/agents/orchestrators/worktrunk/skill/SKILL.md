---
name: worktrunk
description: Git worktree lifecycle management with Worktrunk (wt) for branch-addressed parallel agent workflows.
---

# Worktrunk (`wt`) Git Worktree Management

Worktrunk (`wt`) simplifies working with Git worktrees in multi-agent and parallel development workflows.

## Key Concepts

- Branch-addressed worktrees:
    - Every worktree is named and addressed by its target branch name.
    - Eliminates manual path bookkeeping.
- State preservation:
    - Automatically syncs files listed in `.worktreeinclude` across worktrees.
    - Ideal for sharing local environment configurations, build cache tokens, or staging files.

## Common Commands

```sh
# Switch to or create a worktree for a branch
wt switch feature/my-new-feature

# List all active worktrees
wt list

# Remove a worktree after merging or finishing work
wt remove feature/my-new-feature

# Run a command across all worktrees
wt for-each git status
```
