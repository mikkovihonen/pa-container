from __future__ import annotations

import functools
import sys

sys.dont_write_bytecode = True

"""Secret resolution module for host environment variables and OS keyring."""


from logging_driver import LogCategory, get_category_logger

logger = get_category_logger(__name__, LogCategory.SECURITY)

DEFAULT_KEYRING_SERVICE = "pa-container"

# In-process registry of secrets resolved by trusted host-side components
# (e.g. ACP plugins). Values here come straight from the OS keyring or a host
# CLI session probe — never from environment variables or files.
_resolved_secrets: dict[str, str] = {}


def register_resolved_secret(name: str, value: str) -> None:
    """Register a secret resolved by a trusted host-side component.

    The proxy container pulls ``${ENV:VAR}`` references from this registry
    when the OS keyring has no account named after the variable (custom
    keyring accounts, host CLI session probes).
    """
    _resolved_secrets[name] = value


def get_resolved_secret(name: str) -> str | None:
    """Retrieve a registered resolved secret, if present."""
    return _resolved_secrets.get(name)


def clear_resolved_secrets() -> None:
    """Drop all registered resolved secrets (used by tests and teardown)."""
    _resolved_secrets.clear()


def all_resolved_secrets() -> dict[str, str]:
    """Return a copy of the registry (used for fail-closed leak scanning)."""
    return dict(_resolved_secrets)


@functools.cache
def get_keyring_secret(
    account: str,
    service: str = DEFAULT_KEYRING_SERVICE,
) -> str | None:
    """Retrieve a secret directly from the OS keyring without checking environment variables.

    Results are cached per-process to avoid redundant Keychain accesses and
    system authorization prompts on macOS.
    """
    try:
        import keyring

        secret = keyring.get_password(service, account)
        if secret:
            logger.debug(f"Resolved secret from keyring (service='{service}', account='{account}')")
            return secret

    except Exception as e:
        logger.debug(f"Keyring lookup failed for service='{service}', account='{account}': {e}")

    return None
