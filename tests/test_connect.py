"""Tests for ``bleak_smlight.connect``."""

from __future__ import annotations

from pysmlight import BleProxyClient

from bleak_smlight.backend.scanner import SMLIGHTScanner
from bleak_smlight.connect import (
    SLZB_BLE_SERVER_PORT,
    SMLIGHTClientData,
    connect_scanner,
)

SOURCE = "AA:BB:CC:DD:EE:FF"
NAME = "slzb-proxy"
HOST = "10.0.0.5"


def test_connect_scanner_builds_scanner_and_client() -> None:
    """connect_scanner returns a non-connectable scanner and a proxy client."""
    data = connect_scanner(SOURCE, NAME, HOST)

    assert isinstance(data, SMLIGHTClientData)
    assert isinstance(data.scanner, SMLIGHTScanner)
    assert data.scanner.source == SOURCE
    assert data.scanner.connectable is False
    assert isinstance(data.client, BleProxyClient)
    assert data.client.esp32_ip == HOST
    assert data.client.esp32_port == SLZB_BLE_SERVER_PORT


def test_connect_scanner_honours_custom_port() -> None:
    """A custom UDP port is passed through to the proxy client."""
    data = connect_scanner(SOURCE, NAME, HOST, port=6000)
    assert data.client.esp32_port == 6000


def test_connect_scanner_wires_callback_to_scanner() -> None:
    """The proxy client's callback is the scanner's raw-advert handler."""
    data = connect_scanner(SOURCE, NAME, HOST)
    assert data.client.callback == data.scanner._handle_raw_advertisement
