"""Bluetooth scanner for SMLIGHT SLZB BLE proxy devices."""

from __future__ import annotations

import asyncio
import logging
import math
from typing import TYPE_CHECKING, Any

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

# ``pysmlight`` packs the active-window timeout into an unsigned 16-bit
# millisecond field, so the firmware cannot hold a window open longer.
_MAX_ACTIVE_WINDOW_MS = 65535


def _proxy_ready(client: BleProxyClient) -> bool:
    """
    Whether the proxy has acknowledged the client's PING.

    Every outbound command on ``BleProxyClient`` — ``set_scan_mode``,
    ``set_active_window`` — is guarded by ``if self.transport:`` with no
    ``else``, so before the proxy answers it sends nothing and raises
    nothing. ``transport`` itself is not a usable readiness signal: it is
    assigned from a ``create_datagram_endpoint`` bind on ``0.0.0.0`` that
    never contacts the device. The ACK behind this event is the only proof
    the device replied.

    ``pysmlight`` exposes no public "connected" signal; this attribute is
    stable across the supported 0.5.x range and is read in exactly one
    place so a future public accessor is a one-line swap.
    """
    return client._connected_evt.is_set()


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
        self._window_end: float | None = None
        self._pending_mode_push: asyncio.Task[None] | None = None

    def _unsetup(self) -> None:
        """Tear down; drop a mode push still waiting on the handshake."""
        if (task := self._pending_mode_push) is not None:
            self._pending_mode_push = None
            task.cancel()
        super()._unsetup()

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

        The firmware command is deferred while the proxy client has not
        completed its PING/ACK handshake. ``BleProxyClient.start()`` only
        schedules its connect loop, so a mode set right after it returns
        would hit ``set_scan_mode``'s ``if self.transport:`` guard — which
        has no ``else`` — and be dropped without raising. The scanner
        would then report a mode the radio was never told about. The
        deferred push re-reads :attr:`_intent`, so the most recent pin
        wins and repeated calls before the handshake collapse into one. It
        stands down if an active window opened in the meantime, leaving the
        window's restore to deliver the same mode.
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

        if not _proxy_ready(client):
            if self._pending_mode_push is None:
                _LOGGER.debug(
                    "%s: proxy handshake pending; deferring scan mode %s",
                    self.name,
                    mode.name,
                )
                self._pending_mode_push = asyncio.create_task(
                    self._async_push_mode_when_connected(client)
                )
            return

        self._push_mode(client, mode)

    async def _async_push_mode_when_connected(self, client: BleProxyClient) -> None:
        """Send the pinned intent once the proxy has answered the ping."""
        try:
            await client._connected_evt.wait()
        finally:
            self._pending_mode_push = None
        # An active window may already have opened: the same ACK that wakes
        # this task also opens the gate in
        # ``async_request_active_window``, and a scheduler tick already in
        # the ready queue runs before this callback. Pushing now would send
        # the firmware out of a window the scanner still reports as ACTIVE
        # for its full duration — the exact silent divergence this deferral
        # exists to prevent. The window's own restore path sends the live
        # ``_intent``, which is what this push would have sent, so standing
        # down is not a lost command.
        if self._window_end is not None:
            _LOGGER.debug(
                "%s: active window in flight; leaving the deferred scan mode "
                "to the window's restore",
                self.name,
            )
            return
        # ``async_set_scanning_mode`` pins ``_intent`` before it ever
        # creates this task, and nothing clears it, so the latest pin is
        # always available here.
        if TYPE_CHECKING:
            assert self._intent is not None
        self._push_mode(client, self._intent)

    def _push_mode(self, client: BleProxyClient, mode: BluetoothScanningMode) -> None:
        """Send ``mode`` to the firmware; failures are logged, not raised."""
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

    def _arm_active_window(self, client: BleProxyClient, timeout_ms: int) -> bool:
        """Ask the proxy for a ``timeout_ms`` window; ``False`` if it failed."""
        _LOGGER.debug("%s: Requesting active scan window: %d ms", self.name, timeout_ms)
        try:
            client.set_active_window(timeout_ms)
        except Exception as ex:
            _LOGGER.debug("%s: failed to enter active scan window: %s", self.name, ex)
            return False
        return True

    async def async_request_active_window(self, duration: float) -> bool:
        """
        Request an active scan window on the proxy for ``duration`` seconds.

        Called by habluetooth's auto-mode scheduler. The restore mode
        prefers the integration's pinned intent (set via
        :meth:`async_set_scanning_mode`) — so AUTO returns to PASSIVE on
        the firmware even though ``requested_mode`` stays AUTO — and
        falls back to ``requested_mode`` when no intent has been pinned.

        A request that arrives while a window is already open extends it
        rather than opening a second one: re-arming the firmware timer is
        idempotent, so the longer of the two windows wins and a request
        that expires sooner is already covered. Both cases return
        ``True`` — the radio is active for the requested span either
        way. Only the coroutine that opened the window sleeps and
        restores the prior mode.

        The window never outlasts what the firmware was told: the proxy
        timeout is an unsigned 16-bit millisecond field, so a longer
        ``duration`` is clamped and the sleep follows the clamp instead of
        leaving the scanner reporting ACTIVE after the radio went passive.

        Returns ``False`` without touching the reported mode when the
        proxy has not completed its handshake — the command would be
        dropped on the floor, and claiming ACTIVE for a window the radio
        never opened is worse than reporting the request as ignored.

        Windows are also refused unless ``requested_mode`` is still
        AUTO: repinning the scanner does not retire its auto-scan
        worker, so this method is the only place an explicit
        PASSIVE/ACTIVE pin can be honored.
        """
        # habluetooth binds the auto-scan worker at registration time and
        # only retires it when the scanner is unregistered —
        # ``scanner_mode_changed`` notifies manager callbacks, not the
        # scheduler. So a scanner repinned away from AUTO via
        # ``async_set_scanning_mode`` keeps being ticked, and without this
        # guard it would keep flipping the firmware to ACTIVE behind an
        # explicit PASSIVE pin. ``HaScanner`` refuses here for the same
        # reason.
        if self.requested_mode is not BluetoothScanningMode.AUTO:
            return False
        client = self._client
        if client is None:
            return False
        # Defensive: guard the asyncio.sleep against non-finite / negative
        # durations that an external caller might pass. Negative or NaN
        # would otherwise propagate into a confusing scheduler error.
        # Zero is refused too: it would cost an arm/restore packet pair
        # for a window that is over before it opens.
        if not math.isfinite(duration) or duration <= 0:
            return False
        # Arming before the proxy answers would report ACTIVE for the whole
        # window over a radio that never left PASSIVE.
        if not _proxy_ready(client):
            _LOGGER.debug(
                "%s: proxy has not completed its handshake; "
                "ignoring active scan window request",
                self.name,
            )
            return False
        timeout_ms = min(int(duration * 1000), _MAX_ACTIVE_WINDOW_MS)
        window_end = MONOTONIC_TIME() + timeout_ms / 1000

        # Safe: no await between reading and writing ``_window_end``, so
        # asyncio cannot interleave another request and the open-or-extend
        # decision is atomic without a lock.
        if (open_until := self._window_end) is not None:
            if window_end <= open_until:
                return True
            if not self._arm_active_window(client, timeout_ms):
                return False
            self._window_end = window_end
            return True

        prior = self._intent if self._intent is not None else self.requested_mode
        if not self._arm_active_window(client, timeout_ms):
            return False
        self._window_end = window_end
        self.set_current_mode(BluetoothScanningMode.ACTIVE)

        try:
            # Re-read ``_window_end`` every pass so an extension that
            # lands mid-sleep keeps the radio active for its full span.
            while (remaining := self._window_end - MONOTONIC_TIME()) > 0:
                await asyncio.sleep(remaining)
        finally:
            self._window_end = None
            # Honor a live repin (async_set_scanning_mode is sync and
            # lock-free, so it can land mid-window) over the snapshot
            # taken when the window opened. Fall back to the open-time
            # snapshot only when no intent was ever pinned — there
            # requested_mode reports ACTIVE mid-window, so a live read
            # would pin ACTIVE forever.
            target = self._intent if self._intent is not None else prior
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
