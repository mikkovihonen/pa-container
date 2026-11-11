---
name: source-control
description: Source control operations, credentials, and CLI tooling for GitHub, GitLab, Gitea, GitCafe, Azure DevOps, and Bitbucket.
---

# Source Control Integration

## Overview

The `source-control` capability manages authentication credentials, Git credential helpers, and repository automation across popular source code hosting platforms.

Authentication tokens are securely injected from the host OS Keyring (service: `pa-container`) without storing secrets on disk inside the container.

## Automated Credential Helpers

When `source_control.setup_git_credentials` is enabled (default `true`):
- Active provider tokens are automatically configured for standard `git clone`, `git fetch`, and `git push` operations over HTTPS.
- Authentication happens transparently without prompting for credentials.

### GitHub Integration (`gh`)

The GitHub CLI (`gh`) and GitHub MCP server allow managing issues, pull requests, and repository workflows directly.

#### Common Commands

- **List and View Pull Requests**:
    ```bash
    gh pr list
    gh pr view <number>
    ```
- **Create a Pull Request**:
    ```bash
    gh pr create --title "Feature summary" --body "Implementation details"
    ```
- **Query GitHub API**:
    ```bash
    gh api repos/{owner}/{repo}
    ```
- **MCP Server**: The `github` MCP server is registered at runtime and uses `GH_TOKEN`.

### GitLab Integration (`glab`)

The GitLab CLI (`glab`) enables interacting with GitLab projects, merge requests, and pipelines.

#### Common Commands

- **List and View Merge Requests**:
    ```bash
    glab mr list
    glab mr view <id>
    ```
- **Create a Merge Request**:
    ```bash
    glab mr create --title "Feature summary" --description "Implementation details"
    ```
- **Check CI/CD Pipelines**:
    ```bash
    glab ci status
    ```

### Gitea / Forgejo Integration (`tea` / `fj`)

The Gitea CLI (`tea`, aliased to `fj`) enables managing issues, milestones, and pull requests on Gitea and Forgejo instances.

#### Common Commands

- **List Issues and Pull Requests**:
    ```bash
    tea issues
    tea pulls
    ```
- **Inspect Current Repository Context**:
    ```bash
    tea repo show
    ```

### GitCafe Integration (`cafe`)

The GitCafe CLI (`cafe`) is an intelligent assistant for git branch management, commit generation, and code review.

#### Common Commands

- **Run GitCafe CLI**:
    ```bash
    cafe --help
    ```

### Azure DevOps Integration

Provides seamless authentication for Azure DevOps Git remotes (`https://dev.azure.com/`).

#### Credentials

- Automatically injects `AZURE_DEVOPS_EXT_PAT` from the host OS Keyring.
- Transparently configures Git URL rewrite rules for `dev.azure.com` remotes.

### Bitbucket Integration

Provides authentication credentials and proxy access for Bitbucket Cloud (`https://bitbucket.org/`).

#### Credentials

- Automatically injects `BITBUCKET_TOKEN` from the host OS Keyring.
- Whitelists Bitbucket API and Git host egress through the container proxy.
