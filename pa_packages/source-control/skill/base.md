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
