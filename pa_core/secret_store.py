from __future__ import annotations

import functools
import sys

sys.dont_write_bytecode = True

"""Secret resolution module for host environment variables and OS keyring."""


from logging_driver import LogCategory, get_category_logger

logger = get_category_logger(__name__, LogCategory.SECURITY)

DEFAULT_KEYRING_SERVICE = "pa-container"


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
