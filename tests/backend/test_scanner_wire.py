"""
End-to-end wire-protocol contract tests for ``SMLIGHTScanner``.

These tests feed real SLZB UDP datagrams through ``pysmlight``'s own
``BleProxyProtocol`` decoder into the scanner callback, rather than calling
``_handle_raw_advertisement`` with pre-decoded arguments. That locks the full
``datagram -> pysmlight -> SMLIGHTScanner -> habluetooth`` contract: if
``pysmlight`` ever changes how it reverses the MAC, decodes the signed RSSI, or
orders the callback arguments, these tests break loudly instead of the library
silently forwarding garbage.
"""

from __future__ import annotations

import pytest
from habluetooth import get_manager
from pysmlight import BleProxyProtocol

from bleak_smlight.backend.scanner import SMLIGHTScanner

from .conftest import PROXY_SOURCE

# Raw advertisement payload (flags + service data + mfr data) as it travels
# inside the SLZB DATA datagram, after the 10-byte proxy header.
RAW_ADV = bytes.fromhex(
    "020104030307fe18ff9705060016702500ca00000800000000000000020a00"
)
DEVICE_MAC = "EC:81:CC:F5:75:0C"


def _data_datagram(device_mac: str, rssi: int, address_type: int) -> bytes:
    """
    Build a SLZB ``DATA`` UDP datagram for ``device_mac``.

    Mirrors the wire layout decoded in ``pysmlight.ble_proxy``: a version
    byte (0), an action byte (3 == DATA), six MAC bytes in reverse order, an
    address-type byte, an unsigned RSSI byte (two's-complement of the signed
    value), then the raw advertisement payload.
    """
    mac_bytes = bytes(int(part, 16) for part in reversed(device_mac.split(":")))
    return bytes([0, 3, *mac_bytes, address_type, rssi & 0xFF]) + RAW_ADV


def _feed(scanner: SMLIGHTScanner, datagram: bytes) -> None:
    """Push ``datagram`` through pysmlight's decoder into ``scanner``."""
    protocol = BleProxyProtocol(scanner._handle_raw_advertisement, lambda: None)
    protocol.datagram_received(datagram, ("10.0.0.5", 5050))


def test_data_datagram_reaches_manager(scanner: SMLIGHTScanner) -> None:
    """A decoded DATA datagram surfaces as a service info on the manager."""
    _feed(scanner, _data_datagram(DEVICE_MAC, -72, 1))

    service_info = get_manager().async_last_service_info(DEVICE_MAC, False)
    assert service_info is not None
    assert service_info.address == DEVICE_MAC
    assert service_info.rssi == -72
    assert service_info.source == PROXY_SOURCE


def test_address_type_survives_the_wire(scanner: SMLIGHTScanner) -> None:
    """The proxy-reported address type round-trips into the device details."""
    _feed(scanner, _data_datagram(DEVICE_MAC, -55, 0))

    found = scanner.get_discovered_device_advertisement_data(DEVICE_MAC)
    assert found is not None
    device, _adv = found
    assert device.details["address_type"] == 0
    assert device.details["source"] == PROXY_SOURCE


@pytest.mark.parametrize("rssi", [-100, -72, -1, 0, 20, 127])
def test_signed_rssi_decoding(scanner: SMLIGHTScanner, rssi: int) -> None:
    """The unsigned RSSI byte decodes back to its signed value end-to-end."""
    _feed(scanner, _data_datagram(DEVICE_MAC, rssi, 1))

    service_info = get_manager().async_last_service_info(DEVICE_MAC, False)
    assert service_info is not None
    assert service_info.rssi == rssi
