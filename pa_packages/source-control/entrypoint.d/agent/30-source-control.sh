#!/bin/bash
# Sourced inside agent session to configure source control credential helpers

if [ "${SETUP_GIT_CREDENTIALS:-true}" = "true" ]; then
    # GitHub CLI helper
    if [ -n "${GH_TOKEN:-}" ] && command -v gh >/dev/null 2>&1; then
        gh auth setup-git >/dev/null 2>&1 || true
    fi

    # GitLab CLI helper
    if [ -n "${GITLAB_TOKEN:-}" ] && command -v glab >/dev/null 2>&1; then
        glab auth setup-git >/dev/null 2>&1 || true
    fi

    # Azure DevOps PAT helper for git operations
    if [ -n "${AZURE_DEVOPS_EXT_PAT:-}" ]; then
        git config --global url."https://${AZURE_DEVOPS_EXT_PAT}@dev.azure.com/".insteadOf "https://dev.azure.com/" >/dev/null 2>&1 || true
    fi
fi
