#!/bin/bash
# Staging recipe for ai-frameworks capability: LangGraph, PydanticAI, and smolagents
set -euo pipefail
PA_STAGE="${PA_STAGE:-/out}"

mkdir -p "${PA_STAGE}/usr/local/bin" "${PA_STAGE}/usr/local/lib"

# Install frameworks using uv staged from python package into target prefix
echo "Installing LangGraph, PydanticAI, and smolagents into staging prefix..."
uv pip install --prefix="${PA_STAGE}/usr/local" langgraph pydantic-ai smolagents

# Verification in staging environment
echo "Verifying imports against staging tree..."
SITE_PACKAGES="$(find "${PA_STAGE}/usr/local" -type d -name "site-packages" | head -n 1)"
PYTHONPATH="${SITE_PACKAGES}:${PYTHONPATH:-}" python3 -c "import langgraph, pydantic_ai, smolagents; print('=== ai-frameworks staging verified ===')"

echo "=== ai-frameworks capability build complete ==="
