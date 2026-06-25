"""Bluetooth scanner for SMLIGHT SLZB BLE proxy devices."""

from __future__ import annotations

from bluetooth_data_tools import monotonic_time_coarse as MONOTONIC_TIME
from habluetooth.base_scanner import BaseHaRemoteScanner


class SMLIGHTScanner(BaseHaRemoteScanner):
    """
    Remote scanner fed by a SMLIGHT SLZB BLE proxy.

    The SLZB firmware only relays raw BLE advertisements over UDP; it has
    no GATT/active-connection support, so the scanner is always registered
    as non-connectable and has no client to talk back to.
    """

    def _handle_raw_advertisement(
        self,
        device_mac: str,
        rssi: int,
        address_type: int,
        raw_data: bytes,
    ) -> None:
        """
        Forward one proxied advertisement to habluetooth.

        This is the callback handed to ``pysmlight.BleProxyClient``. The
        proxy client already decodes the MAC into the canonical
        ``AA:BB:CC:DD:EE:FF`` string and converts the RSSI to a signed
        ``int``, so the values can be passed straight through without any
        further conversion.
        """
        self._async_on_raw_advertisement(
            device_mac,
            rssi,
            raw_data,
            {"address_type": address_type},
            MONOTONIC_TIME(),
        )
