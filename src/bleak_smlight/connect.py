"""Bluetooth proxy support for SMLIGHT SLZB devices."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from pysmlight import BleProxyClient

from .backend.scanner import SMLIGHTScanner

_LOGGER = logging.getLogger(__name__)

# Default UDP port of the SLZB BLE proxy server (SLZB-OS).
SLZB_BLE_SERVER_PORT = 5050


@dataclass(slots=True)
class SMLIGHTClientData:
    """The scanner and its BLE proxy client for one SLZB device."""

    scanner: SMLIGHTScanner
    client: BleProxyClient


def connect_scanner(
    source: str,
    name: str,
    host: str,
    port: int = SLZB_BLE_SERVER_PORT,
) -> SMLIGHTClientData:
    """
    Build a scanner and BLE proxy client for an SLZB device.

    ``source`` is the stable unique identifier for the proxy (typically
    its MAC address); ``name`` is the human-friendly adapter name;
    ``host`` is the IP/hostname the UDP proxy server listens on.

    The caller is responsible for:

    1. Calling ``data.scanner.async_setup()``.
    2. Registering ``data.scanner`` with the habluetooth manager (and
       unregistering it on teardown).
    3. Calling ``await data.client.start()`` to begin receiving
       advertisements, and ``data.client.stop()`` on teardown.

    :class:`SMLIGHTConnectionManager` wires all of this up for the common
    standalone case.
    """
    _LOGGER.debug("%s [%s]: Connecting scanner to %s:%s", name, source, host, port)
    scanner = SMLIGHTScanner(source, name, None, False)
    client = BleProxyClient(
        esp32_ip=host,
        callback=scanner._handle_raw_advertisement,
        esp32_port=port,
    )
    return SMLIGHTClientData(scanner=scanner, client=client)
