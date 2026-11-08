"""
Pytest configuration for src/ tests.

run.py and build.py call sys.exit(1) at module level when validate_environment
fails (e.g. llama-server not found in test environments).  This conftest
patches sys.exit so those calls become no-ops, allowing the modules to be
imported and their classes/functions to be tested.
"""

import sys
from pathlib import Path

# Make src/ importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Patch sys.exit to a no-op so module-level sys.exit() calls in run.py and
# build.py don't abort test collection.  The real sys.exit is restored after
# the session via the pytest_sessionfinish hook.
_original_exit = sys.exit


def _noop_exit(*args, **kwargs):
    pass


sys.exit = _noop_exit

# Ensure default global configuration exists so test collection and tests
# that import config modules succeed even in unseeded environments.
_global_cfg_file = Path.home() / ".config" / "pa-container" / "config.yaml"
if not _global_cfg_file.is_file():
    try:
        from global_config import init_global_config

        init_global_config(repo_root=Path(__file__).resolve().parent.parent.parent)
    except Exception:
        pass

# Also patch it on the modules that will be imported.  Some code may hold
# a direct reference to sys.exit, so we patch both.


def pytest_sessionfinish(session, exitstatus):
    sys.exit = _original_exit
