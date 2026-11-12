from __future__ import annotations

import sys
from typing import TypedDict

sys.dont_write_bytecode = True


class SourceControlProviderConfig(TypedDict, total=False):
    """Configuration for a specific source control provider."""

    keyring_var: str | list[str]
    keyring_service: str


class SourceControlConfig(TypedDict, total=False):
    """Configuration schema for source control credentials and integrations."""

    enabled: bool
    auto_detect_host_cli: bool
    setup_git_credentials: bool
    providers: dict[str, SourceControlProviderConfig]
