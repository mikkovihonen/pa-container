from __future__ import annotations

import sys
from unittest.mock import patch

import pytest

import secret_store

sys.dont_write_bytecode = True

"""Unit tests for pa_core/secret_store.py."""


@pytest.fixture(autouse=True)
def _clear_keyring_cache():
    """Clear the lru_cache on get_keyring_secret between tests."""
    secret_store.get_keyring_secret.cache_clear()
    yield
    secret_store.get_keyring_secret.cache_clear()


def test_get_keyring_secret_success():
    with patch("keyring.get_password", return_value="secret_pwd") as mock_get:
        val = secret_store.get_keyring_secret("my_account", service="my_service")
        assert val == "secret_pwd"
        mock_get.assert_called_once_with("my_service", "my_account")


def test_get_keyring_secret_failure():
    with patch("keyring.get_password", side_effect=RuntimeError("Keyring unavailable")):
        val = secret_store.get_keyring_secret("my_account")
        assert val is None


def test_get_keyring_secret_not_found():
    with patch("keyring.get_password", return_value=None) as mock_get:
        val = secret_store.get_keyring_secret("MISSING_KEY")
        assert val is None
        mock_get.assert_called_once_with(secret_store.DEFAULT_KEYRING_SERVICE, "MISSING_KEY")


def test_get_keyring_secret_for_admin_password():
    with patch("keyring.get_password", return_value="secure_admin_pass") as mock_get:
        val = secret_store.get_keyring_secret("ADMIN_PASSWORD")
        assert val == "secure_admin_pass"
        mock_get.assert_called_once_with(secret_store.DEFAULT_KEYRING_SERVICE, "ADMIN_PASSWORD")


@pytest.fixture(autouse=True)
def _clear_resolved_registry():
    """Keep the in-process resolved-secret registry isolated between tests."""
    secret_store.clear_resolved_secrets()
    yield
    secret_store.clear_resolved_secrets()


def test_register_and_get_resolved_secret():
    assert secret_store.get_resolved_secret("GH_TOKEN") is None
    secret_store.register_resolved_secret("GH_TOKEN", "gh_real_token")
    assert secret_store.get_resolved_secret("GH_TOKEN") == "gh_real_token"


def test_register_overwrites_previous_value():
    secret_store.register_resolved_secret("GH_TOKEN", "first")
    secret_store.register_resolved_secret("GH_TOKEN", "second")
    assert secret_store.get_resolved_secret("GH_TOKEN") == "second"


def test_all_resolved_secrets_returns_copy():
    secret_store.register_resolved_secret("GH_TOKEN", "gh_real_token")
    snapshot = secret_store.all_resolved_secrets()
    assert snapshot == {"GH_TOKEN": "gh_real_token"}
    snapshot["GH_TOKEN"] = "mutated"
    assert secret_store.get_resolved_secret("GH_TOKEN") == "gh_real_token"


def test_clear_resolved_secrets():
    secret_store.register_resolved_secret("GH_TOKEN", "gh_real_token")
    secret_store.clear_resolved_secrets()
    assert secret_store.get_resolved_secret("GH_TOKEN") is None
    assert secret_store.all_resolved_secrets() == {}
