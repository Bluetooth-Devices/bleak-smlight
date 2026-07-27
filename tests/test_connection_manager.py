"""Tests for ``bleak_smlight.connection_manager``."""

from __future__ import annotations

import asyncio
from typing import cast
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from habluetooth import BluetoothScanningMode
from pysmlight import BleProxyClient, BleProxyMode

from bleak_smlight.backend.scanner import SMLIGHTScanner
from bleak_smlight.connection_manager import (
    SMLIGHTConnectionManager,
    SMLIGHTDeviceConfig,
)


@pytest.fixture
def config() -> SMLIGHTDeviceConfig:
    """Return a minimal device config used across tests."""
    return {"source": "AA:BB:CC:DD:EE:FF", "name": "slzb-proxy", "host": "10.0.0.5"}


def test_construct_without_running_loop_is_side_effect_free(
    config: SMLIGHTDeviceConfig,
) -> None:
    """Construction needs no event loop and creates no proxy client."""
    manager = SMLIGHTConnectionManager(config)
    assert manager._client is None
    assert manager._unregister_scanner is None
    assert manager._unsetup_scanner is None
    assert manager._port == 5050


def test_config_custom_port_is_used() -> None:
    """An explicit ``port`` in the config overrides the default."""
    manager = SMLIGHTConnectionManager(
        {"source": "s", "name": "n", "host": "h", "port": 6000}
    )
    assert manager._port == 6000


@pytest.mark.asyncio
async def test_start_registers_scanner_and_starts_client(
    config: SMLIGHTDeviceConfig,
) -> None:
    """start() sets up the scanner, registers it, and starts the client."""
    scanner = Mock()
    unsetup = Mock()
    scanner.async_setup = Mock(return_value=unsetup)
    client = Mock()
    client.start = AsyncMock()
    data = Mock(scanner=scanner, client=client)
    unregister = Mock()
    ha_manager = Mock()
    ha_manager.async_register_scanner = Mock(return_value=unregister)

    with (
        patch(
            "bleak_smlight.connection_manager.connect_scanner", return_value=data
        ) as connect_scanner_mock,
        patch("bleak_smlight.connection_manager.get_manager", return_value=ha_manager),
    ):
        manager = SMLIGHTConnectionManager(config)
        await manager.start()

    connect_scanner_mock.assert_called_once_with(
        "AA:BB:CC:DD:EE:FF", "slzb-proxy", "10.0.0.5", 5050, None
    )
    scanner.async_setup.assert_called_once_with()
    ha_manager.async_register_scanner.assert_called_once_with(scanner)
    client.start.assert_awaited_once_with()
    scanner.async_set_scanning_mode.assert_not_called()
    assert manager._client is client
    assert manager._unregister_scanner is unregister
    assert manager._unsetup_scanner is unsetup


@pytest.mark.asyncio
async def test_start_applies_configured_mode(config: SMLIGHTDeviceConfig) -> None:
    """
    A configured mode is seeded before registration and pinned after start.

    habluetooth binds the auto-scan scheduler when the scanner registers and
    only for a scanner already reporting AUTO, so the mode has to reach
    ``connect_scanner``; the firmware command needs a running proxy client,
    so it is pinned after ``client.start()``.
    """
    scanner = Mock()
    scanner.async_setup = Mock(return_value=Mock())
    client = Mock()
    client.start = AsyncMock()
    data = Mock(scanner=scanner, client=client)
    ha_manager = Mock()
    calls: list[str] = []

    def _register(_scanner):
        calls.append("register")
        return Mock()

    ha_manager.async_register_scanner = Mock(side_effect=_register)
    client.start = AsyncMock(side_effect=lambda: calls.append("client_start"))
    scanner.async_set_scanning_mode = Mock(
        side_effect=lambda _mode: calls.append("set")
    )

    with (
        patch(
            "bleak_smlight.connection_manager.connect_scanner", return_value=data
        ) as connect_scanner_mock,
        patch("bleak_smlight.connection_manager.get_manager", return_value=ha_manager),
    ):
        manager = SMLIGHTConnectionManager(
            {**config, "mode": BluetoothScanningMode.AUTO}
        )
        await manager.start()

    connect_scanner_mock.assert_called_once_with(
        "AA:BB:CC:DD:EE:FF", "slzb-proxy", "10.0.0.5", 5050, BluetoothScanningMode.AUTO
    )
    scanner.async_set_scanning_mode.assert_called_once_with(BluetoothScanningMode.AUTO)
    assert calls == ["register", "client_start", "set"]


def _real_scanner(mode: BluetoothScanningMode) -> tuple[SMLIGHTScanner, MagicMock]:
    """A real scanner wired to a proxy client that has not answered yet."""
    scanner = SMLIGHTScanner(
        "AA:BB:CC:DD:EE:FF", "slzb-proxy", None, False, requested_mode=mode
    )
    client = MagicMock(spec=BleProxyClient)
    client._connected_evt = asyncio.Event()
    client.start = AsyncMock()
    scanner.set_client(client)
    return scanner, client


@pytest.mark.asyncio
async def test_mode_push_waits_for_the_proxy_handshake(
    config: SMLIGHTDeviceConfig,
) -> None:
    """
    The configured mode reaches the firmware only after the proxy's ACK.

    ``BleProxyClient.start()`` only schedules its connect loop, so a mode
    set when it returns hits ``set_scan_mode``'s ``if self.transport:``
    guard and is dropped without raising. The scanner owns that deferral;
    the manager hands the mode over and lets it wait.
    """
    scanner, client = _real_scanner(BluetoothScanningMode.ACTIVE)
    data = Mock(scanner=scanner, client=client)

    with (
        patch("bleak_smlight.connection_manager.connect_scanner", return_value=data),
        patch("bleak_smlight.connection_manager.get_manager", return_value=MagicMock()),
    ):
        manager = SMLIGHTConnectionManager(
            {**config, "mode": BluetoothScanningMode.ACTIVE}
        )
        await manager.start()
        await asyncio.sleep(0)
        client.set_scan_mode.assert_not_called()

        client._connected_evt.set()
        await asyncio.sleep(0)
        client.set_scan_mode.assert_called_once_with(BleProxyMode.BLE_PROXY_MODE_ACTIVE)
        await manager.stop()


@pytest.mark.asyncio
async def test_configured_mode_stands_down_for_an_in_flight_window(
    config: SMLIGHTDeviceConfig,
) -> None:
    """
    A window opened on the same ACK keeps the radio; the mode push stands down.

    The auto-scan scheduler and the deferred mode push both wake on the
    proxy's handshake. If the scheduler wins, sending the configured mode
    would drop the firmware out of a window the scanner still reports as
    ACTIVE for its full duration, and every device in that window goes
    unscanned. Routing the manager's mode through the scanner is what puts
    it behind that guard.
    """
    scanner, client = _real_scanner(BluetoothScanningMode.AUTO)
    data = Mock(scanner=scanner, client=client)

    with (
        patch("bleak_smlight.connection_manager.connect_scanner", return_value=data),
        patch("bleak_smlight.connection_manager.get_manager", return_value=MagicMock()),
    ):
        manager = SMLIGHTConnectionManager(
            {**config, "mode": BluetoothScanningMode.AUTO}
        )
        await manager.start()
        # Let the deferred push suspend on the handshake before the
        # scheduler's window is queued, so the window runs first.
        await asyncio.sleep(0)
        window = asyncio.create_task(scanner.async_request_active_window(30))
        client._connected_evt.set()
        await asyncio.sleep(0)

        client.set_active_window.assert_called_once_with(30000)
        assert scanner.current_mode is BluetoothScanningMode.ACTIVE
        client.set_scan_mode.assert_not_called()

        window.cancel()
        await manager.stop()


@pytest.mark.asyncio
async def test_stop_cancels_a_pending_mode_push(config: SMLIGHTDeviceConfig) -> None:
    """A manager stopped before the proxy answers leaves no waiting task."""
    scanner, client = _real_scanner(BluetoothScanningMode.PASSIVE)
    data = Mock(scanner=scanner, client=client)

    with (
        patch("bleak_smlight.connection_manager.connect_scanner", return_value=data),
        patch("bleak_smlight.connection_manager.get_manager", return_value=MagicMock()),
    ):
        manager = SMLIGHTConnectionManager(
            {**config, "mode": BluetoothScanningMode.PASSIVE}
        )
        await manager.start()
        task = scanner._pending_mode_push
        assert task is not None
        await manager.stop()

        client._connected_evt.set()
        await asyncio.sleep(0)
        assert task.cancelled()
    client.set_scan_mode.assert_not_called()


@pytest.mark.asyncio
async def test_start_twice_raises_runtime_error(config: SMLIGHTDeviceConfig) -> None:
    """A second start() raises rather than leaking the prior proxy client."""
    data = Mock(scanner=Mock(async_setup=Mock(return_value=Mock())), client=Mock())
    data.client.start = AsyncMock()

    with (
        patch("bleak_smlight.connection_manager.connect_scanner", return_value=data),
        patch("bleak_smlight.connection_manager.get_manager", return_value=MagicMock()),
    ):
        manager = SMLIGHTConnectionManager(config)
        await manager.start()
        with pytest.raises(RuntimeError, match="already been called"):
            await manager.start()


@pytest.mark.asyncio
async def test_stop_tears_down_in_order(config: SMLIGHTDeviceConfig) -> None:
    """stop() stops the client and clears scanner registration callbacks."""
    scanner = Mock()
    unsetup = Mock()
    scanner.async_setup = Mock(return_value=unsetup)
    client = Mock()
    client.start = AsyncMock()
    data = Mock(scanner=scanner, client=client)
    unregister = Mock()
    ha_manager = Mock()
    ha_manager.async_register_scanner = Mock(return_value=unregister)

    with (
        patch("bleak_smlight.connection_manager.connect_scanner", return_value=data),
        patch("bleak_smlight.connection_manager.get_manager", return_value=ha_manager),
    ):
        manager = SMLIGHTConnectionManager(config)
        await manager.start()
        await manager.stop()

    client.stop.assert_called_once_with()
    unregister.assert_called_once_with()
    unsetup.assert_called_once_with()
    assert manager._client is None
    assert cast(object, manager._unregister_scanner) is None
    assert cast(object, manager._unsetup_scanner) is None


@pytest.mark.asyncio
async def test_scanner_property_exposes_registered_scanner(
    config: SMLIGHTDeviceConfig,
) -> None:
    """``scanner`` is the registered scanner only while the manager runs."""
    scanner = Mock()
    scanner.async_setup = Mock(return_value=Mock())
    client = Mock()
    client.start = AsyncMock()
    data = Mock(scanner=scanner, client=client)

    with (
        patch("bleak_smlight.connection_manager.connect_scanner", return_value=data),
        patch("bleak_smlight.connection_manager.get_manager", return_value=MagicMock()),
    ):
        manager = SMLIGHTConnectionManager(config)
        before = manager.scanner
        await manager.start()
        during = manager.scanner
        await manager.stop()
        after = manager.scanner

    assert (before, during, after) == (None, scanner, None)


@pytest.mark.asyncio
async def test_stop_before_start_is_noop(config: SMLIGHTDeviceConfig) -> None:
    """stop() is safe to call on a manager that was never started."""
    manager = SMLIGHTConnectionManager(config)
    await manager.stop()
    assert manager._client is None


@pytest.mark.asyncio
async def test_stop_unregisters_scanner_even_if_client_stop_raises(
    config: SMLIGHTDeviceConfig,
) -> None:
    """A failing client.stop() still unregisters and unsets the scanner."""
    scanner = Mock()
    unsetup = Mock()
    scanner.async_setup = Mock(return_value=unsetup)
    client = Mock()
    client.start = AsyncMock()
    client.stop = Mock(side_effect=RuntimeError("transport already closed"))
    data = Mock(scanner=scanner, client=client)
    unregister = Mock()
    ha_manager = Mock()
    ha_manager.async_register_scanner = Mock(return_value=unregister)

    with (
        patch("bleak_smlight.connection_manager.connect_scanner", return_value=data),
        patch("bleak_smlight.connection_manager.get_manager", return_value=ha_manager),
    ):
        manager = SMLIGHTConnectionManager(config)
        await manager.start()
        with pytest.raises(RuntimeError, match="transport already closed"):
            await manager.stop()

    # The scanner is torn down despite the client failure, so the manager is
    # left in a clean stopped state rather than leaking the registration.
    unregister.assert_called_once_with()
    unsetup.assert_called_once_with()
    assert manager._client is None
    assert cast(object, manager._unregister_scanner) is None
    assert cast(object, manager._unsetup_scanner) is None
