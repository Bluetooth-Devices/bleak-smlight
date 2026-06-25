"""Tests for the top-level ``bleak_smlight`` package surface."""

from __future__ import annotations

import bleak_smlight
from bleak_smlight import (
    SLZB_BLE_SERVER_PORT,
    SMLIGHTClientData,
    SMLIGHTConnectionManager,
    SMLIGHTDeviceConfig,
    connect_scanner,
)
from bleak_smlight.connect import SLZB_BLE_SERVER_PORT as _PORT_impl
from bleak_smlight.connect import SMLIGHTClientData as _SMLIGHTClientData_impl
from bleak_smlight.connect import connect_scanner as _connect_scanner_impl
from bleak_smlight.connection_manager import (
    SMLIGHTConnectionManager as _SMLIGHTConnectionManager_impl,
)
from bleak_smlight.connection_manager import (
    SMLIGHTDeviceConfig as _SMLIGHTDeviceConfig_impl,
)


def test_public_all_matches_module_exports() -> None:
    """``__all__`` must list exactly the names re-exported at package root."""
    assert set(bleak_smlight.__all__) == {
        "SLZB_BLE_SERVER_PORT",
        "SMLIGHTClientData",
        "SMLIGHTConnectionManager",
        "SMLIGHTDeviceConfig",
        "__version__",
        "connect_scanner",
    }
    for name in bleak_smlight.__all__:
        assert hasattr(bleak_smlight, name), name


def test_public_reexports_resolve_to_canonical_objects() -> None:
    """Re-exports must be the same objects as their canonical definitions."""
    assert connect_scanner is _connect_scanner_impl
    assert SMLIGHTClientData is _SMLIGHTClientData_impl
    assert SMLIGHTConnectionManager is _SMLIGHTConnectionManager_impl
    assert SMLIGHTDeviceConfig is _SMLIGHTDeviceConfig_impl
    assert SLZB_BLE_SERVER_PORT is _PORT_impl


def test_version_is_a_string() -> None:
    """``__version__`` is exposed as a string."""
    assert isinstance(bleak_smlight.__version__, str)
