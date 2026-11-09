---
name: gh
description: Interact with GitHub repositories, inspect issues, create pull requests, and query API endpoints using the GitHub CLI.
---

# GitHub CLI (gh)

## Common Commands

### 1. View Issues and Pull Requests
```bash
gh issue list
gh pr list
gh pr view <number>
```

### 2. Create Pull Requests
```bash
gh pr create --title "Feature description" --body "Detailed changes..."
```

### 3. API Queries
```bash
gh api repos/{owner}/{repo}
```
