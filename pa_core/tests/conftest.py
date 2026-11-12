"""Pytest configuration for pa_core/ tests."""

import sys
from pathlib import Path

# Make pa_core/ importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Ensure default global configuration exists so test collection and tests
# that import config modules succeed even in unseeded environments.
_global_cfg_file = Path.home() / ".config" / "pa-container" / "config.yaml"
if not _global_cfg_file.is_file():
    try:
        from global_config import init_global_config

        init_global_config(repo_root=Path(__file__).resolve().parent.parent.parent)
    except Exception:
        pass
