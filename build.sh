#!/usr/bin/env bash
# Builds the pa-container-agent image.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec uv run --project "$SCRIPT_DIR" python "$SCRIPT_DIR/src/cli.py" build "$@"
