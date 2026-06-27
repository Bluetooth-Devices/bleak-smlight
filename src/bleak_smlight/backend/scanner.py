"""Bluetooth scanner for SMLIGHT SLZB BLE proxy devices."""

from __future__ import annotations

import asyncio
import logging
import math
from typing import Any

from bluetooth_data_tools import (
    int_to_bluetooth_address,
)
from bluetooth_data_tools import (
    monotonic_time_coarse as MONOTONIC_TIME,
)
from habluetooth import BluetoothScanningMode
from habluetooth.base_scanner import BaseHaRemoteScanner
from pysmlight import BleProxyClient, BleProxyMode

_LOGGER = logging.getLogger(__name__)

_HA_TO_FIRMWARE_MODE: dict[BluetoothScanningMode, BleProxyMode] = {
    BluetoothScanningMode.ACTIVE: BleProxyMode.BLE_PROXY_MODE_ACTIVE,
    BluetoothScanningMode.PASSIVE: BleProxyMode.BLE_PROXY_MODE_PASSIVE,
    BluetoothScanningMode.AUTO: BleProxyMode.BLE_PROXY_MODE_PASSIVE,
}


class SMLIGHTScanner(BaseHaRemoteScanner):
    """
    Remote scanner fed by a SMLIGHT SLZB BLE proxy.

    The SLZB firmware only relays raw BLE advertisements over UDP; it has
    no GATT/active-connection support, so the scanner is always registered
    as non-connectable.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the scanner."""
        super().__init__(*args, **kwargs)
        self._client: BleProxyClient | None = None
        self._intent: BluetoothScanningMode | None = None
        self._active_window_lock = asyncio.Lock()

    def set_client(self, client: BleProxyClient) -> None:
        """
        Bind the BLE proxy client to send configuration requests.

        Required for ``async_request_active_window`` and
        ``async_set_scanning_mode`` to actually contact the proxy;
        without it, requests are silently ignored.
        """
        self._client = client

    def async_set_scanning_mode(self, mode: BluetoothScanningMode) -> None:
        """
        Pin the scanner to ``mode`` and tell the firmware.

        AUTO maps to PASSIVE on the firmware; the auto-scheduler flips it
        to ACTIVE on demand via :meth:`async_request_active_window`.

        Unlike ESPHome scanners, the firmware does not push spontaneous
        scanner-state or mode update packets back to the client. While the
        firmware sends ACK packets to acknowledge configuration commands, the
        integration currently ignores them as they may be ambiguous. Therefore,
        the local scanner tracks and pins the requested/current modes entirely
        locally based on the integration's intent.
        """
        self._intent = mode
        self.set_requested_mode(mode)
        self.set_current_mode(mode)

        client = self._client
        if client is None:
            _LOGGER.warning(
                "%s: Cannot set scanner mode to %s on the proxy;",
                self.name,
                mode.name,
            )
            return

        firmware_mode = _HA_TO_FIRMWARE_MODE.get(
            mode, BleProxyMode.BLE_PROXY_MODE_PASSIVE
        )
        _LOGGER.debug(
            "%s: Setting scan mode: intent=%s, firmware_mode=%s",
            self.name,
            mode.name,
            firmware_mode.name,
        )
        try:
            client.set_scan_mode(firmware_mode)
        except Exception as ex:
            _LOGGER.debug("%s: failed to set scan mode: %s", self.name, ex)

    async def async_request_active_window(self, duration: float) -> bool:
        """
        Request an active scan window on the proxy for ``duration`` seconds.

        Called by habluetooth's auto-mode scheduler. The restore mode
        prefers the integration's pinned intent (set via
        :meth:`async_set_scanning_mode`) — so AUTO returns to PASSIVE on
        the firmware even though ``requested_mode`` stays AUTO — and
        falls back to the last known ``requested_mode`` when no intent has
        been pinned. If no prior mode is known the proxy is returned to
        PASSIVE.

        Only one window may be open at a time; a request that arrives while
        another window is in flight returns ``False`` immediately so the
        caller can decide whether to retry.
        """
        client = self._client
        if client is None:
            return False
        # Defensive: guard the asyncio.sleep against non-finite / negative
        # durations that an external caller might pass. Negative or NaN
        # would otherwise propagate into a confusing scheduler error.
        if not math.isfinite(duration) or duration < 0:
            return False
        # Safe: no await between the .locked() check and the acquire
        # inside `async with`, so asyncio cannot schedule another
        # coroutine in between and the check / acquire is effectively
        # atomic on this lock.
        if self._active_window_lock.locked():
            return False
        async with self._active_window_lock:
            prior = self._intent if self._intent is not None else self.requested_mode

            # Request active scan window (convert duration to milliseconds)
            timeout_ms = min(int(duration * 1000), 65535)
            _LOGGER.debug(
                "%s: Requesting active scan window: duration=%.3fs (%d ms)",
                self.name,
                duration,
                timeout_ms,
            )
            try:
                client.set_active_window(timeout_ms)
            except Exception as ex:
                _LOGGER.debug(
                    "%s: failed to enter active scan window: %s", self.name, ex
                )
                return False
            self.set_current_mode(BluetoothScanningMode.ACTIVE)

            try:
                await asyncio.sleep(duration)
            finally:
                # Honor a live repin (async_set_scanning_mode is sync and
                # lock-free, so it can land mid-window) over the snapshot
                # taken when the window opened. Fall back to the open-time
                # snapshot only when no intent was ever pinned — there
                # requested_mode reports ACTIVE mid-window, so a live read
                # would pin ACTIVE forever.
                target = self._intent if self._intent is not None else prior
                if target is None:
                    target = BluetoothScanningMode.PASSIVE
                self.set_current_mode(target)
                restore = _HA_TO_FIRMWARE_MODE.get(
                    target, BleProxyMode.BLE_PROXY_MODE_PASSIVE
                )
                _LOGGER.debug(
                    "%s: Active scan window finished. Restoring scan mode: "
                    "target=%s, firmware_mode=%s",
                    self.name,
                    target.name,
                    restore.name,
                )
                try:
                    client.set_scan_mode(restore)
                except Exception as ex:
                    _LOGGER.warning(
                        "%s: failed to restore scan mode after active window: %s",
                        self.name,
                        ex,
                    )
        return True

    def _handle_raw_advertisement(
        self,
        mac_bytes: bytes,
        rssi: int,
        address_type: int,
        raw_data: bytes,
    ) -> None:
        """
        Forward one proxied advertisement to habluetooth.

        This is the callback handed to ``pysmlight.BleProxyClient``. A single
        UDP packet from the proxy may package multiple advertisements; these
        are unbundled by ``pysmlight``'s proxy client protocol and passed here
        individually. The raw 6-byte MAC address is converted to a
        colon-separated uppercase string via `int_to_bluetooth_address` in
        Cython space to optimize performance.
        """
        device_mac = int_to_bluetooth_address(
            int.from_bytes(mac_bytes, byteorder="little")
        )

        self._async_on_raw_advertisement(
            device_mac,
            rssi,
            raw_data,
            {"address_type": address_type},
            MONOTONIC_TIME(),
        )
