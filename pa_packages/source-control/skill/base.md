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
