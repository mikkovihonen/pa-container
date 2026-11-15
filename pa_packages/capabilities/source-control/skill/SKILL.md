---
name: source-control
description: "Use when creating branches, pull requests, merge requests, reviewing code diffs, or synchronizing repositories across GitHub, GitLab, Bitbucket, and Azure DevOps."
---

# Source Control Automation (`source-control`)

Extends core `git` with multi-forge automation workflows for managing branches, reviews, and pull/merge requests across enterprise Git platforms.

## Forge Integration Overview

| Platform | Primary Authentication Token | Key Hostnames |
|---|---|---|
| **GitHub** | `GITHUB_TOKEN` | `github.com`, `api.github.com` |
| **GitLab** | `GITLAB_TOKEN` | `gitlab.com` |
| **Bitbucket** | `BITBUCKET_TOKEN` | `bitbucket.org` |
| **Azure DevOps** | `AZURE_DEVOPS_EXT_PAT` | `dev.azure.com` |

## Common Recipes

### GitHub Pull Request Lifecycle

```sh
# Push feature branch
git push origin feature/my-feature

# Create PR via GitHub CLI
gh pr create --title "feat: descriptive summary" --body "Detailed description of changes"
```

### GitLab Merge Request via Git Push Options

GitLab supports opening merge requests directly over Git push options without requiring dedicated CLI tools:

```sh
git push origin feature/my-feature \
    -o merge_request.create \
    -o merge_request.target=main \
    -o merge_request.title="feat: descriptive summary" \
    -o merge_request.remove_source_branch
```

### Azure DevOps Git Workflow

```sh
# Authenticate via Personal Access Token
git -c http.extraHeader="Authorization: Basic $(echo -n ":$AZURE_DEVOPS_EXT_PAT" | base64)" fetch origin
```

## Guidelines
- **Token Security**: Tokens are HMAC-managed placeholder secrets dynamically injected by the proxy. Never write raw tokens to disk or commit them into git history.
- **Atomic Commits**: Group related changes logically and maintain clean commit histories with conventional commit prefixes (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`).
