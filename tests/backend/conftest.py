"""Shared fixtures for ``tests/backend``."""

from __future__ import annotations

import pytest

from bleak_smlight.backend.scanner import SMLIGHTScanner

PROXY_SOURCE = "AA:BB:CC:DD:EE:FF"
PROXY_NAME = "slzb-proxy"


@pytest.fixture
def scanner() -> SMLIGHTScanner:
    """Return a non-connectable ``SMLIGHTScanner`` for the standard proxy."""
    return SMLIGHTScanner(PROXY_SOURCE, PROXY_NAME, None, False)
