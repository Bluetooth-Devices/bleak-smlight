"""Shared fixtures for the ``bleak_smlight`` test suite."""

from __future__ import annotations

import pytest
from bleak_retry_connector import BleakSlotManager
from bluetooth_adapters import BluetoothAdapters
from habluetooth import BluetoothManager, set_manager


@pytest.fixture(scope="session", autouse=True)
def manager() -> None:
    """Install a real habluetooth manager so scanners can register."""
    slot_manager = BleakSlotManager()
    bluetooth_adapters = BluetoothAdapters()
    set_manager(BluetoothManager(bluetooth_adapters, slot_manager))
