"""Tests for ``bleak_smlight.connection_manager``."""

from __future__ import annotations

from typing import cast
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

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
        "AA:BB:CC:DD:EE:FF", "slzb-proxy", "10.0.0.5", 5050
    )
    scanner.async_setup.assert_called_once_with()
    ha_manager.async_register_scanner.assert_called_once_with(scanner)
    client.start.assert_awaited_once_with()
    assert manager._client is client
    assert manager._unregister_scanner is unregister
    assert manager._unsetup_scanner is unsetup


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
async def test_stop_before_start_is_noop(config: SMLIGHTDeviceConfig) -> None:
    """stop() is safe to call on a manager that was never started."""
    manager = SMLIGHTConnectionManager(config)
    await manager.stop()
    assert manager._client is None


@pytest.mark.asyncio
async def test_start_rolls_back_scanner_setup_when_register_fails(
    config: SMLIGHTDeviceConfig,
) -> None:
    """A failing scanner registration tears down the scanner setup."""
    scanner = Mock()
    unsetup = Mock()
    scanner.async_setup = Mock(return_value=unsetup)
    client = Mock()
    client.start = AsyncMock()
    data = Mock(scanner=scanner, client=client)
    ha_manager = Mock()
    ha_manager.async_register_scanner = Mock(side_effect=RuntimeError("dup source"))

    with (
        patch("bleak_smlight.connection_manager.connect_scanner", return_value=data),
        patch("bleak_smlight.connection_manager.get_manager", return_value=ha_manager),
    ):
        manager = SMLIGHTConnectionManager(config)
        with pytest.raises(RuntimeError, match="dup source"):
            await manager.start()

    unsetup.assert_called_once_with()
    client.start.assert_not_awaited()
    # The manager is left clean so the caller can retry with a new instance.
    assert manager._client is None
    assert cast(object, manager._unsetup_scanner) is None
    assert cast(object, manager._unregister_scanner) is None


@pytest.mark.asyncio
async def test_start_rolls_back_registration_when_client_start_fails(
    config: SMLIGHTDeviceConfig,
) -> None:
    """A failing client.start() unregisters and tears down the scanner."""
    scanner = Mock()
    unsetup = Mock()
    scanner.async_setup = Mock(return_value=unsetup)
    client = Mock()
    client.start = AsyncMock(side_effect=OSError("boom"))
    data = Mock(scanner=scanner, client=client)
    unregister = Mock()
    ha_manager = Mock()
    ha_manager.async_register_scanner = Mock(return_value=unregister)

    with (
        patch("bleak_smlight.connection_manager.connect_scanner", return_value=data),
        patch("bleak_smlight.connection_manager.get_manager", return_value=ha_manager),
    ):
        manager = SMLIGHTConnectionManager(config)
        with pytest.raises(OSError, match="boom"):
            await manager.start()

    unregister.assert_called_once_with()
    unsetup.assert_called_once_with()
    assert manager._client is None
    assert cast(object, manager._unsetup_scanner) is None
    assert cast(object, manager._unregister_scanner) is None


@pytest.mark.asyncio
async def test_async_context_manager_starts_and_stops(
    config: SMLIGHTDeviceConfig,
) -> None:
    """`async with` starts on entry, yields the manager, and stops on exit."""
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
        async with manager as entered:
            assert entered is manager
            client.start.assert_awaited_once_with()
            client.stop.assert_not_called()

    client.stop.assert_called_once_with()
    unregister.assert_called_once_with()
    unsetup.assert_called_once_with()
    assert manager._client is None
