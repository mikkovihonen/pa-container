---
name: source-control
description: Source control operations, credentials, and CLI tooling for GitHub, GitLab, Gitea, GitCafe, Azure DevOps, and Bitbucket.
---

# Source Control Integration

## Overview

The `source-control` capability manages authentication credentials, Git credential helpers, and repository automation across popular source code hosting platforms.

## Automated Credential Helpers

When `source_control.setup_git_credentials` is enabled (default `true`):
- Git credential helpers are configured for standard `git clone`, `git fetch`, and `git push` operations over HTTPS.
- The helpers send the placeholder token. The proxy replaces it with the real token before the request leaves the sandbox.
- Authentication happens transparently without prompting for credentials.
