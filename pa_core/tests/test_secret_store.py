from __future__ import annotations

import sys
from unittest.mock import patch

import secret_store

sys.dont_write_bytecode = True

"""Unit tests for pa_core/secret_store.py."""


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
