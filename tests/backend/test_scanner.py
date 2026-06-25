"""Tests for ``bleak_smlight.backend.scanner``."""

from __future__ import annotations

from habluetooth import BaseHaRemoteScanner, get_manager

from bleak_smlight.backend.scanner import SMLIGHTScanner

from .conftest import PROXY_SOURCE

# A real raw advertisement payload (flags + service data + mfr data).
RAW_ADV = (
    b"\x02\x01\x04\x03\x03\x07\xfe\x18\xff\x97\x05\x06\x00\x16p%\x00"
    b"\xca\x00\x00\x08\x00\x00\x00\x00\x00\x00\x00\x02\n\x00"
)
DEVICE_MAC = "EC:81:CC:F5:75:0C"


def test_scanner_is_remote_and_non_connectable(scanner: SMLIGHTScanner) -> None:
    """The scanner is a non-connectable remote scanner."""
    assert isinstance(scanner, BaseHaRemoteScanner)
    assert scanner.connectable is False
    assert scanner.source == PROXY_SOURCE


def test_handle_raw_advertisement_feeds_manager(scanner: SMLIGHTScanner) -> None:
    """A proxied advertisement is parsed and reaches the habluetooth manager."""
    scanner._handle_raw_advertisement(DEVICE_MAC, -72, 1, RAW_ADV)

    service_info = get_manager().async_last_service_info(DEVICE_MAC, False)
    assert service_info is not None
    assert service_info.address == DEVICE_MAC
    assert service_info.rssi == -72
    assert service_info.source == PROXY_SOURCE


def test_handle_raw_advertisement_records_address_type(
    scanner: SMLIGHTScanner,
) -> None:
    """The proxy-reported address type is preserved in the device details."""
    scanner._handle_raw_advertisement(DEVICE_MAC, -88, 1, RAW_ADV)

    found = scanner.get_discovered_device_advertisement_data(DEVICE_MAC)
    assert found is not None
    device, _adv = found
    assert device.details["address_type"] == 1
    assert device.details["source"] == PROXY_SOURCE
