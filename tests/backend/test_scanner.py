"""Tests for ``bleak_smlight.backend.scanner``."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from habluetooth import BaseHaRemoteScanner, BluetoothScanningMode, get_manager
from pysmlight import BleProxyClient, BleProxyMode

from bleak_smlight.backend.scanner import SMLIGHTScanner

from .conftest import PROXY_SOURCE

# A real raw advertisement payload (flags + service data + mfr data).
RAW_ADV = (
    b"\x02\x01\x04\x03\x03\x07\xfe\x18\xff\x97\x05\x06\x00\x16p%\x00"
    b"\xca\x00\x00\x08\x00\x00\x00\x00\x00\x00\x00\x02\n\x00"
)
DEVICE_MAC = "EC:81:CC:F5:75:0C"
DEVICE_MAC_BYTES = b"\x0c\x75\xf5\xcc\x81\xec"


def _connected_client() -> MagicMock:
    """A proxy client mock whose PING/ACK handshake has completed."""
    client = _pending_client()
    client._connected_evt.set()
    return client


def _pending_client() -> MagicMock:
    """A proxy client mock that has not yet been answered by the proxy."""
    client = MagicMock(spec=BleProxyClient)
    client._connected_evt = asyncio.Event()
    return client


def test_scanner_is_remote_and_non_connectable(scanner: SMLIGHTScanner) -> None:
    """The scanner is a non-connectable remote scanner."""
    assert isinstance(scanner, BaseHaRemoteScanner)
    assert scanner.connectable is False
    assert scanner.source == PROXY_SOURCE


def test_handle_raw_advertisement_feeds_manager(scanner: SMLIGHTScanner) -> None:
    """A proxied advertisement is parsed and reaches the habluetooth manager."""
    scanner._handle_raw_advertisement(DEVICE_MAC_BYTES, -72, 1, RAW_ADV)

    service_info = get_manager().async_last_service_info(DEVICE_MAC, False)
    assert service_info is not None
    assert service_info.address == DEVICE_MAC
    assert service_info.rssi == -72
    assert service_info.source == PROXY_SOURCE


def test_handle_raw_advertisement_records_address_type(
    scanner: SMLIGHTScanner,
) -> None:
    """The proxy-reported address type is preserved in the device details."""
    scanner._handle_raw_advertisement(DEVICE_MAC_BYTES, -88, 1, RAW_ADV)

    found = scanner.get_discovered_device_advertisement_data(DEVICE_MAC)
    assert found is not None
    device, _adv = found
    assert device.details["address_type"] == 1
    assert device.details["source"] == PROXY_SOURCE


@pytest.mark.parametrize(
    ("scanning_mode", "expected_firmware_mode"),
    [
        pytest.param(
            BluetoothScanningMode.ACTIVE,
            BleProxyMode.BLE_PROXY_MODE_ACTIVE,
            id="active_mode",
        ),
        pytest.param(
            BluetoothScanningMode.PASSIVE,
            BleProxyMode.BLE_PROXY_MODE_PASSIVE,
            id="passive_mode",
        ),
        pytest.param(
            BluetoothScanningMode.AUTO,
            BleProxyMode.BLE_PROXY_MODE_PASSIVE,
            id="auto_mode",
        ),
    ],
)
def test_set_scanning_mode(
    scanner: SMLIGHTScanner,
    scanning_mode: BluetoothScanningMode,
    expected_firmware_mode: BleProxyMode,
) -> None:
    """Test updating scanning mode tells the client and updates state."""
    client = _connected_client()
    scanner.set_client(client)

    scanner.async_set_scanning_mode(scanning_mode)
    assert scanner.requested_mode == scanning_mode
    assert scanner.current_mode == scanning_mode
    client.set_scan_mode.assert_called_once_with(expected_firmware_mode)


def test_set_scanning_mode_no_client(scanner: SMLIGHTScanner) -> None:
    """Test set scanning mode when client is None."""
    scanner.async_set_scanning_mode(BluetoothScanningMode.ACTIVE)
    assert scanner.requested_mode == BluetoothScanningMode.ACTIVE
    assert scanner.current_mode == BluetoothScanningMode.ACTIVE


@pytest.mark.asyncio
async def test_async_request_active_window(scanner: SMLIGHTScanner) -> None:
    """Test requesting active scan window."""
    client = _connected_client()
    scanner.set_client(client)
    scanner.async_set_scanning_mode(BluetoothScanningMode.PASSIVE)
    client.reset_mock()

    success = await scanner.async_request_active_window(0.05)
    assert success is True

    client.set_active_window.assert_called_once_with(50)  # 0.05s -> 50ms
    client.set_scan_mode.assert_called_once_with(BleProxyMode.BLE_PROXY_MODE_PASSIVE)


@pytest.mark.asyncio
async def test_async_request_active_window_clamping(scanner: SMLIGHTScanner) -> None:
    """Test active window duration clamping to 65535 ms."""
    client = _connected_client()
    scanner.set_client(client)

    with patch("asyncio.sleep") as mock_sleep:
        success = await scanner.async_request_active_window(70.0)
        assert success is True
        mock_sleep.assert_called_once_with(70.0)

    client.set_active_window.assert_called_once_with(65535)


@pytest.mark.asyncio
async def test_async_request_active_window_invalid(scanner: SMLIGHTScanner) -> None:
    """Test active window requests with invalid parameters."""
    client = _connected_client()
    scanner.set_client(client)

    assert await scanner.async_request_active_window(-1.0) is False
    assert await scanner.async_request_active_window(float("inf")) is False
    assert await scanner.async_request_active_window(float("nan")) is False

    client.set_active_window.assert_not_called()


@pytest.mark.asyncio
async def test_async_request_active_window_no_client(scanner: SMLIGHTScanner) -> None:
    """Test active window request when no client is set."""
    assert await scanner.async_request_active_window(0.1) is False


@pytest.mark.asyncio
async def test_async_request_active_window_locked(scanner: SMLIGHTScanner) -> None:
    """Test concurrent active window requests are rejected."""
    client = _connected_client()
    scanner.set_client(client)

    async def run_request() -> bool:
        return await scanner.async_request_active_window(0.1)

    task1 = asyncio.create_task(run_request())
    await asyncio.sleep(0.01)

    success2 = await scanner.async_request_active_window(0.05)
    assert success2 is False

    success1 = await task1
    assert success1 is True


@pytest.mark.asyncio
async def test_async_request_active_window_restore_failure(
    scanner: SMLIGHTScanner,
) -> None:
    """Test exception handling during scan mode restore."""
    client = _connected_client()
    client.set_scan_mode.side_effect = RuntimeError("Failed to restore")
    scanner.set_client(client)

    success = await scanner.async_request_active_window(0.01)
    assert success is True
    client.set_active_window.assert_called_once()
    client.set_scan_mode.assert_called_once_with(BleProxyMode.BLE_PROXY_MODE_PASSIVE)


def test_async_set_scanning_mode_error(scanner: SMLIGHTScanner) -> None:
    """Test exception handling in async_set_scanning_mode."""
    client = _connected_client()
    client.set_scan_mode.side_effect = RuntimeError("Failed to set scan mode")
    scanner.set_client(client)

    scanner.async_set_scanning_mode(BluetoothScanningMode.ACTIVE)
    assert scanner.requested_mode == BluetoothScanningMode.ACTIVE
    assert scanner.current_mode == BluetoothScanningMode.ACTIVE


@pytest.mark.asyncio
async def test_async_request_active_window_error(scanner: SMLIGHTScanner) -> None:
    """Test exception handling when set_active_window fails."""
    client = _connected_client()
    client.set_active_window.side_effect = RuntimeError(
        "Failed to request active window"
    )
    scanner.set_client(client)

    success = await scanner.async_request_active_window(0.01)
    assert success is False
    client.set_active_window.assert_called_once()


@pytest.mark.asyncio
async def test_set_scanning_mode_defers_until_handshake(
    scanner: SMLIGHTScanner,
) -> None:
    """
    A mode set before the proxy answers is sent after the handshake.

    ``BleProxyClient.start()`` only schedules its connect loop, so
    ``set_scan_mode`` would hit its ``if self.transport:`` guard and
    drop the packet without raising.
    """
    client = _pending_client()
    scanner.set_client(client)

    scanner.async_set_scanning_mode(BluetoothScanningMode.ACTIVE)
    await asyncio.sleep(0)
    client.set_scan_mode.assert_not_called()
    assert scanner.requested_mode is BluetoothScanningMode.ACTIVE

    client._connected_evt.set()
    await asyncio.sleep(0)
    client.set_scan_mode.assert_called_once_with(BleProxyMode.BLE_PROXY_MODE_ACTIVE)


@pytest.mark.asyncio
async def test_deferred_mode_push_sends_only_the_latest_intent(
    scanner: SMLIGHTScanner,
) -> None:
    """Repins before the handshake collapse into one push of the last one."""
    client = _pending_client()
    scanner.set_client(client)

    scanner.async_set_scanning_mode(BluetoothScanningMode.ACTIVE)
    scanner.async_set_scanning_mode(BluetoothScanningMode.PASSIVE)

    client._connected_evt.set()
    await asyncio.sleep(0)
    client.set_scan_mode.assert_called_once_with(BleProxyMode.BLE_PROXY_MODE_PASSIVE)


@pytest.mark.asyncio
async def test_set_scanning_mode_after_handshake_is_immediate(
    scanner: SMLIGHTScanner,
) -> None:
    """Once connected the command goes out synchronously, with no task."""
    client = _connected_client()
    scanner.set_client(client)

    unsetup = scanner.async_setup()

    scanner.async_set_scanning_mode(BluetoothScanningMode.PASSIVE)
    client.set_scan_mode.assert_called_once_with(BleProxyMode.BLE_PROXY_MODE_PASSIVE)
    assert scanner._pending_mode_push is None

    unsetup()


@pytest.mark.asyncio
async def test_unsetup_cancels_a_pending_mode_push(scanner: SMLIGHTScanner) -> None:
    """Tearing the scanner down drops a push still waiting on the proxy."""
    client = _pending_client()
    scanner.set_client(client)
    unsetup = scanner.async_setup()

    scanner.async_set_scanning_mode(BluetoothScanningMode.ACTIVE)
    task = scanner._pending_mode_push
    assert task is not None

    unsetup()
    assert scanner._pending_mode_push is None

    client._connected_evt.set()
    await asyncio.sleep(0)
    assert task.cancelled()
    client.set_scan_mode.assert_not_called()
