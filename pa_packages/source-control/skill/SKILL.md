---
name: source-control
description: Source control operations, credentials, and CLI tooling for GitHub, GitLab, Gitea, GitCafe, Azure DevOps, and Bitbucket.
---

# Source Control Integration

## Overview

The `source-control` capability manages authentication credentials, Git credential helpers, and repository automation across popular source code hosting platforms.

The container environment holds **placeholder tokens only** (for example, `GH_TOKEN=GH_TOKEN_PLACEHOLDER`). Real tokens stay on the host: `pa run` reads them from the OS Keyring (service: `pa-container`) and registers them with the egress proxy. The proxy substitutes the placeholders in outgoing HTTP traffic, including base64-encoded `Basic` credentials sent by git. No real credential is stored or printed inside the container.

## Automated Credential Helpers

When `source_control.setup_git_credentials` is enabled (default `true`):
- Git credential helpers are configured for standard `git clone`, `git fetch`, and `git push` operations over HTTPS.
- The helpers send the placeholder token. The proxy replaces it with the real token before the request leaves the sandbox.
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
- **MCP Server**: The `github` MCP server is registered at runtime and uses the `GH_TOKEN` placeholder, which the proxy substitutes in outgoing requests.

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

- Injects the `AZURE_DEVOPS_EXT_PAT` placeholder into the container. The proxy substitutes the real token from the host OS Keyring in outgoing requests.
- Transparently configures Git URL rewrite rules for `dev.azure.com` remotes.

### Bitbucket Integration

Provides authentication credentials and proxy access for Bitbucket Cloud (`https://bitbucket.org/`).

#### Credentials

- Injects the `BITBUCKET_TOKEN` placeholder into the container. The proxy substitutes the real token from the host OS Keyring in outgoing requests.
- Whitelists Bitbucket API and Git host egress through the container proxy.
