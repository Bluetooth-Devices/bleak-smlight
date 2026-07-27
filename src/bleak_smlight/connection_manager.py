"""Standalone connection manager for a SMLIGHT SLZB BLE proxy."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, NotRequired, TypedDict

from habluetooth import get_manager

from .connect import SLZB_BLE_SERVER_PORT, connect_scanner

if TYPE_CHECKING:
    from collections.abc import Callable

    from habluetooth import BluetoothScanningMode
    from pysmlight import BleProxyClient

    from .backend.scanner import SMLIGHTScanner

_LOGGER = logging.getLogger(__name__)

# How often to re-check for the proxy client's UDP transport before
# pushing the configured mode. The connect loop creates the endpoint on
# its first pass, so this normally resolves on the first tick.
_TRANSPORT_POLL_INTERVAL = 0.1


class SMLIGHTDeviceConfig(TypedDict):
    """Configuration for one SMLIGHT SLZB BLE proxy device."""

    source: str
    name: str
    host: str
    port: NotRequired[int]
    mode: NotRequired[BluetoothScanningMode]


class SMLIGHTConnectionManager:
    """
    Manage a scanner for a SMLIGHT SLZB BLE proxy.

    Construction is side-effect-free and does not require a running event
    loop; all asyncio work happens in :meth:`start`. The underlying
    ``BleProxyClient`` owns its own connect/retry loop, so the manager only
    has to register the scanner with the habluetooth manager and start the
    proxy client.
    """

    def __init__(self, config: SMLIGHTDeviceConfig) -> None:
        """Initialize the connection manager from ``config``."""
        self._source = config["source"]
        self._name = config["name"]
        self._host = config["host"]
        self._port = config.get("port", SLZB_BLE_SERVER_PORT)
        self._mode = config.get("mode")
        self._client: BleProxyClient | None = None
        self._scanner: SMLIGHTScanner | None = None
        self._mode_task: asyncio.Task[None] | None = None
        self._unregister_scanner: Callable[[], None] | None = None
        self._unsetup_scanner: Callable[[], None] | None = None

    @property
    def scanner(self) -> SMLIGHTScanner | None:
        """
        The registered scanner, or ``None`` before ``start()`` / after ``stop()``.

        This is the handle for scan-mode control — the scanner owns
        ``async_set_scanning_mode``, which repins PASSIVE/ACTIVE at
        runtime. Switching to ``AUTO`` here only pins it locally: the
        scheduler that drives active windows is bound at registration
        time, so ``AUTO`` belongs in the config's ``mode``.
        """
        return self._scanner

    async def start(self) -> None:
        """
        Build the scanner, register it, and start the BLE proxy client.

        Call once per manager instance; a second call raises
        ``RuntimeError`` rather than leaking the prior proxy client and its
        background reconnect task.

        A configured ``mode`` is seeded on the scanner before it is
        registered (habluetooth binds the auto-scan scheduler there). The
        matching firmware command is handed to a background task, because
        the proxy client has no transport to send it on yet when
        ``start()`` returns; ``start()`` itself stays non-blocking.

        Raises:
            RuntimeError: if :meth:`start` has already been called.

        """
        if self._client is not None:
            raise RuntimeError(
                "SMLIGHTConnectionManager.start() has already been called; "
                "create a new manager instance to reconnect."
            )
        data = connect_scanner(
            self._source, self._name, self._host, self._port, self._mode
        )
        scanner = data.scanner
        self._unsetup_scanner = scanner.async_setup()
        self._unregister_scanner = get_manager().async_register_scanner(scanner)
        self._scanner = scanner
        self._client = data.client
        await self._client.start()
        if self._mode is not None:
            self._mode_task = asyncio.create_task(
                self._push_mode(scanner, data.client, self._mode)
            )

    async def _push_mode(
        self,
        scanner: SMLIGHTScanner,
        client: BleProxyClient,
        mode: BluetoothScanningMode,
    ) -> None:
        """
        Pin ``mode`` once the proxy client has a transport to send it on.

        ``BleProxyClient.start()`` only schedules its connect loop, so the
        UDP endpoint does not exist yet when it returns — and
        ``set_scan_mode`` is a silent no-op while ``transport`` is
        ``None``. Setting the mode inline would therefore pin it locally
        and never reach the firmware. Cancelled by :meth:`stop`.
        """
        while client.transport is None:
            await asyncio.sleep(_TRANSPORT_POLL_INTERVAL)
        scanner.async_set_scanning_mode(mode)

    async def stop(self) -> None:
        """
        Stop the BLE proxy client and unregister the scanner.

        A pending mode push is cancelled first, so a manager stopped
        before the proxy ever answered leaves no task waiting on a
        transport that will never appear.

        Every teardown step runs even if an earlier one raises, so a
        failure stopping the client cannot leave the scanner registered
        (which would block recreating a manager for the same ``source``).
        State is cleared up front, so a failed ``stop()`` still leaves the
        manager in a stopped state. An exception, if any, propagates once all
        steps have run; if several steps raise, they are chained (the last
        surfaces with the earlier ones as its ``__context__``).
        """
        client, self._client = self._client, None
        self._scanner = None
        mode_task, self._mode_task = self._mode_task, None
        if mode_task is not None:
            mode_task.cancel()
        unregister, self._unregister_scanner = self._unregister_scanner, None
        unsetup, self._unsetup_scanner = self._unsetup_scanner, None
        try:
            if client is not None:
                client.stop()
        finally:
            try:
                if unregister is not None:
                    unregister()
            finally:
                if unsetup is not None:
                    unsetup()
