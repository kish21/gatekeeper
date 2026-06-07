"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

from gatekeeper.config import loader

# A valid-looking HMAC key for tests (64 hex chars). NOT a real secret — fixture only.
GOOD_HMAC = "a" * 64


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    """Settings is lru_cached; clear it around each test so env changes take effect."""
    loader.get_settings.cache_clear()
    yield
    loader.get_settings.cache_clear()
