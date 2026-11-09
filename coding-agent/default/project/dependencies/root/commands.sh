#!/bin/bash
set -e

# Root-level commands for project-specific setup.
# This script runs when project specific container image is built.
# Use this for:
#   - Installing system packages: microdnf install -y <package>
#   - Installing npm globals: npm install -g <package>
#   - System configuration that requires root privileges
#
# Example:
#   microdnf install -y ffmpeg
#   npm install -g typescript

echo "Root commands: no-op (project-specific setup not configured)"
