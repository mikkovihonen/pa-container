#!/bin/bash
set -e

# Agent-user commands for project-specific setup.
# This script runs as the agent user during container startup, before the agent launches.
# Use this for:
#   - Initializing Python venvs: python -m venv .venv && .venv/bin/pip install ...
#   - Cloning repositories: git clone <url>
#   - Workspace-specific configuration
#
# Example:
#   python -m venv .venv && .venv/bin/pip install -r requirements.txt
#   git clone https://github.com/example/repo.git

echo "Agent commands: no-op (project-specific setup not configured)"
