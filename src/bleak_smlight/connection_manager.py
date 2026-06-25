"""Standalone connection manager for a SMLIGHT SLZB BLE proxy."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, NotRequired, TypedDict

from habluetooth import get_manager

from .connect import SLZB_BLE_SERVER_PORT, connect_scanner

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import TracebackType

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
        # Build up the registration in stages, unwinding any completed stage if
        # a later one fails. Registering a scanner whose ``source`` is already
        # known raises from habluetooth; without rollback that would leak the
        # scanner's ``async_setup`` teardown and leave a half-started manager
        # that cannot be retried (``_client`` stays ``None`` so a second
        # ``start()`` silently re-runs and leaks again).
        unsetup = scanner.async_setup()
        try:
            unregister = get_manager().async_register_scanner(scanner)
        except BaseException:
            unsetup()
            raise
        try:
            await data.client.start()
        except BaseException:
            unregister()
            unsetup()
            raise
        self._unsetup_scanner = unsetup
        self._unregister_scanner = unregister
        self._client = data.client

    async def stop(self) -> None:
        """Stop the BLE proxy client and unregister the scanner."""
        if self._client is not None:
            self._client.stop()
            self._client = None
        if self._unregister_scanner is not None:
            self._unregister_scanner()
            self._unregister_scanner = None
        if self._unsetup_scanner is not None:
            self._unsetup_scanner()
            self._unsetup_scanner = None

    async def __aenter__(self) -> SMLIGHTConnectionManager:
        """Start the manager on entry and return it."""
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Stop the manager on exit, regardless of how the block exited."""
        await self.stop()
