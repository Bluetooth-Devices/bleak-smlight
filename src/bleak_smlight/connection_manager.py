"""Standalone connection manager for a SMLIGHT SLZB BLE proxy."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, NotRequired, TypedDict

from habluetooth import get_manager

from .connect import SLZB_BLE_SERVER_PORT, connect_scanner

if TYPE_CHECKING:
    from collections.abc import Callable

    from pysmlight import BleProxyClient

_LOGGER = logging.getLogger(__name__)


class SMLIGHTDeviceConfig(TypedDict):
    """Configuration for one SMLIGHT SLZB BLE proxy device."""

    source: str
    name: str
    host: str
    port: NotRequired[int]


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
        self._client: BleProxyClient | None = None
        self._unregister_scanner: Callable[[], None] | None = None
        self._unsetup_scanner: Callable[[], None] | None = None

    async def start(self) -> None:
        """
        Build the scanner, register it, and start the BLE proxy client.

        Call once per manager instance; a second call raises
        ``RuntimeError`` rather than leaking the prior proxy client and its
        background reconnect task.

        Raises:
            RuntimeError: if :meth:`start` has already been called.

        """
        if self._client is not None:
            raise RuntimeError(
                "SMLIGHTConnectionManager.start() has already been called; "
                "create a new manager instance to reconnect."
            )
        data = connect_scanner(self._source, self._name, self._host, self._port)
        scanner = data.scanner
        self._unsetup_scanner = scanner.async_setup()
        self._unregister_scanner = get_manager().async_register_scanner(scanner)
        self._client = data.client
        await self._client.start()

    async def stop(self) -> None:
        """
        Stop the BLE proxy client and unregister the scanner.

        Every teardown step runs even if an earlier one raises, so a
        failure stopping the client cannot leave the scanner registered
        (which would block recreating a manager for the same ``source``).
        State is cleared up front, so a failed ``stop()`` still leaves the
        manager in a stopped state. An exception, if any, propagates once all
        steps have run; if several steps raise, they are chained (the last
        surfaces with the earlier ones as its ``__context__``).
        """
        client, self._client = self._client, None
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
