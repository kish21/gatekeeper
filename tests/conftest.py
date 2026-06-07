"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

from gatekeeper.config import loader


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    """Settings is lru_cached; clear it around each test so env changes take effect."""
    loader.get_settings.cache_clear()
    yield
    loader.get_settings.cache_clear()
