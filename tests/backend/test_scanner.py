"""Tests for ``bleak_smlight.backend.scanner``."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, call

import pytest
from bluetooth_data_tools import monotonic_time_coarse
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
async def test_async_request_active_window(auto_scanner: SMLIGHTScanner) -> None:
    """Test requesting active scan window."""
    client = _connected_client()
    auto_scanner.set_client(client)

    success = await auto_scanner.async_request_active_window(0.05)
    assert success is True

    client.set_active_window.assert_called_once_with(50)  # 0.05s -> 50ms
    client.set_scan_mode.assert_called_once_with(BleProxyMode.BLE_PROXY_MODE_PASSIVE)


@pytest.mark.asyncio
async def test_async_request_active_window_clamping(
    auto_scanner: SMLIGHTScanner,
) -> None:
    """A duration past the 16-bit ms ceiling clamps the window, sleep included."""
    client = _connected_client()
    auto_scanner.set_client(client)

    task = asyncio.create_task(auto_scanner.async_request_active_window(120.0))
    await asyncio.sleep(0)

    client.set_active_window.assert_called_once_with(65535)
    # The scanner must not keep reporting ACTIVE past the clamp: the
    # firmware falls back to passive at 65.535s regardless of the 120s
    # the caller asked for.
    assert auto_scanner.current_mode == BluetoothScanningMode.ACTIVE
    assert auto_scanner._window_end is not None
    assert auto_scanner._window_end - monotonic_time_coarse() == pytest.approx(
        65.535, abs=0.05
    )

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    client.set_scan_mode.assert_called_once_with(BleProxyMode.BLE_PROXY_MODE_PASSIVE)


@pytest.mark.asyncio
async def test_async_request_active_window_invalid(
    auto_scanner: SMLIGHTScanner,
) -> None:
    """Test active window requests with invalid parameters."""
    client = _connected_client()
    auto_scanner.set_client(client)

    assert await auto_scanner.async_request_active_window(-1.0) is False
    assert await auto_scanner.async_request_active_window(0.0) is False
    assert await auto_scanner.async_request_active_window(float("inf")) is False
    assert await auto_scanner.async_request_active_window(float("nan")) is False

    client.set_active_window.assert_not_called()


@pytest.mark.asyncio
async def test_async_request_active_window_no_client(
    auto_scanner: SMLIGHTScanner,
) -> None:
    """Test active window request when no client is set."""
    assert await auto_scanner.async_request_active_window(0.1) is False


@pytest.mark.asyncio
async def test_shorter_overlapping_request_is_covered(
    auto_scanner: SMLIGHTScanner,
) -> None:
    """A request expiring inside the open window is satisfied by it."""
    client = _connected_client()
    auto_scanner.set_client(client)

    task = asyncio.create_task(auto_scanner.async_request_active_window(0.2))
    await asyncio.sleep(0)

    assert await auto_scanner.async_request_active_window(0.05) is True
    # Already active for longer than the second caller asked for, so the
    # firmware timer is left alone.
    client.set_active_window.assert_called_once_with(200)

    assert await task is True
    client.set_scan_mode.assert_called_once_with(BleProxyMode.BLE_PROXY_MODE_PASSIVE)


@pytest.mark.asyncio
async def test_longer_overlapping_request_extends_the_window(
    auto_scanner: SMLIGHTScanner,
) -> None:
    """A request outlasting the open window re-arms the firmware timer."""
    client = _connected_client()
    auto_scanner.set_client(client)

    started = monotonic_time_coarse()
    task = asyncio.create_task(auto_scanner.async_request_active_window(0.05))
    await asyncio.sleep(0)

    assert await auto_scanner.async_request_active_window(0.3) is True
    assert client.set_active_window.call_args_list == [call(50), call(300)]

    assert await task is True
    # One sleeper, one restore — the extension did not open a second
    # window, and the radio stayed active for the longer span.
    assert monotonic_time_coarse() - started >= 0.25
    client.set_scan_mode.assert_called_once_with(BleProxyMode.BLE_PROXY_MODE_PASSIVE)


@pytest.mark.asyncio
async def test_overlapping_request_failing_to_extend_returns_false(
    auto_scanner: SMLIGHTScanner,
) -> None:
    """A failed re-arm reports False and leaves the open window untouched."""
    client = _connected_client()
    auto_scanner.set_client(client)

    task = asyncio.create_task(auto_scanner.async_request_active_window(0.05))
    await asyncio.sleep(0)
    open_until = auto_scanner._window_end

    client.set_active_window.side_effect = RuntimeError("proxy unreachable")
    assert await auto_scanner.async_request_active_window(0.3) is False
    assert auto_scanner._window_end == open_until

    assert await task is True


@pytest.mark.asyncio
async def test_async_request_active_window_restore_failure(
    auto_scanner: SMLIGHTScanner,
) -> None:
    """Test exception handling during scan mode restore."""
    client = _connected_client()
    client.set_scan_mode.side_effect = RuntimeError("Failed to restore")
    auto_scanner.set_client(client)

    success = await auto_scanner.async_request_active_window(0.01)
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
async def test_async_request_active_window_error(auto_scanner: SMLIGHTScanner) -> None:
    """Test exception handling when set_active_window fails."""
    client = _connected_client()
    client.set_active_window.side_effect = RuntimeError(
        "Failed to request active window"
    )
    auto_scanner.set_client(client)

    success = await auto_scanner.async_request_active_window(0.01)
    assert success is False
    client.set_active_window.assert_called_once()


@pytest.mark.asyncio
async def test_active_window_before_handshake_is_reported_as_ignored(
    auto_scanner: SMLIGHTScanner,
) -> None:
    """A window requested before the proxy answers is refused, not faked."""
    client = _connected_client()
    client._connected_evt.clear()
    auto_scanner.set_client(client)
    auto_scanner.async_set_scanning_mode(BluetoothScanningMode.AUTO)

    assert await auto_scanner.async_request_active_window(0.05) is False

    # ``set_active_window`` would have been dropped on the floor by
    # pysmlight, so the scanner must not claim the radio went ACTIVE.
    client.set_active_window.assert_not_called()
    assert auto_scanner.current_mode == BluetoothScanningMode.AUTO
    assert auto_scanner._window_end is None


@pytest.mark.asyncio
async def test_repin_away_from_auto_refuses_active_windows(
    auto_scanner: SMLIGHTScanner,
) -> None:
    """A scanner repinned off AUTO refuses the windows its worker still ticks."""
    client = _connected_client()
    auto_scanner.set_client(client)
    auto_scanner.async_set_scanning_mode(BluetoothScanningMode.PASSIVE)
    client.reset_mock()

    # habluetooth only retires the auto-scan worker on unregister, so the
    # scheduler keeps ticking; honoring it would flip the firmware to
    # ACTIVE behind the explicit PASSIVE pin.
    assert await auto_scanner.async_request_active_window(0.05) is False

    client.set_active_window.assert_not_called()
    assert auto_scanner.current_mode == BluetoothScanningMode.PASSIVE
    assert auto_scanner._window_end is None


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


@pytest.mark.asyncio
async def test_deferred_push_stands_down_for_a_window_opened_by_the_same_ack(
    auto_scanner: SMLIGHTScanner,
) -> None:
    """The handshake push must not drop the firmware out of a live window."""
    client = _pending_client()
    auto_scanner.set_client(client)

    auto_scanner.async_set_scanning_mode(BluetoothScanningMode.AUTO)
    assert auto_scanner._pending_mode_push is not None
    # Let the deferred push reach its wait on the handshake event.
    await asyncio.sleep(0)
    client.set_scan_mode.assert_not_called()

    # The single ACK both wakes that push and opens the window gate. Queue
    # the scheduler tick before the ACK so it reaches the gate first — the
    # ordering that puts the stale push inside a live window.
    task = asyncio.create_task(auto_scanner.async_request_active_window(0.05))
    client._connected_evt.set()
    await asyncio.sleep(0)

    assert auto_scanner._window_end is not None
    client.set_active_window.assert_called_once_with(50)
    # A push here would send firmware PASSIVE while the scanner keeps
    # reporting ACTIVE for the rest of the window.
    client.set_scan_mode.assert_not_called()
    assert auto_scanner.current_mode is BluetoothScanningMode.ACTIVE

    assert await task is True
    # The window's own restore delivers the pinned intent — once.
    client.set_scan_mode.assert_called_once_with(BleProxyMode.BLE_PROXY_MODE_PASSIVE)


@pytest.mark.asyncio
async def test_repin_during_a_live_window_stands_down(
    auto_scanner: SMLIGHTScanner,
) -> None:
    """A repin must not drop the firmware out of a window in flight."""
    client = _connected_client()
    auto_scanner.set_client(client)

    task = asyncio.create_task(auto_scanner.async_request_active_window(0.05))
    await asyncio.sleep(0)
    assert auto_scanner._window_end is not None

    # Same rule as the deferred handshake push: the radio is active for
    # the rest of the window, so pushing now would desync the reported
    # mode from the radio. The window's restore delivers this intent.
    auto_scanner.async_set_scanning_mode(BluetoothScanningMode.PASSIVE)
    assert auto_scanner.requested_mode is BluetoothScanningMode.PASSIVE
    # Read through locals so each assertion narrows on its own snapshot;
    # asserting twice on the attribute would let mypy carry the first
    # narrowing across the await and call the second one unreachable.
    mid_window_mode = auto_scanner.current_mode
    assert mid_window_mode is BluetoothScanningMode.ACTIVE
    client.set_scan_mode.assert_not_called()

    assert await task is True
    restored_mode = auto_scanner.current_mode
    assert restored_mode is BluetoothScanningMode.PASSIVE
    client.set_scan_mode.assert_called_once_with(BleProxyMode.BLE_PROXY_MODE_PASSIVE)


@pytest.mark.asyncio
async def test_repin_to_auto_mid_window_keeps_the_extend_path_honest(
    auto_scanner: SMLIGHTScanner,
) -> None:
    """An extend answered True must not sit on a radio a repin sent passive."""
    client = _connected_client()
    auto_scanner.set_client(client)

    task = asyncio.create_task(auto_scanner.async_request_active_window(0.2))
    await asyncio.sleep(0)

    # A repin to AUTO leaves requested_mode AUTO, so the scheduler keeps
    # ticking and the next request takes the extend path. That path
    # answers True without arming anything, so the window it reports has
    # to still be open on the radio.
    auto_scanner.async_set_scanning_mode(BluetoothScanningMode.AUTO)
    assert await auto_scanner.async_request_active_window(0.05) is True
    client.set_scan_mode.assert_not_called()
    client.set_active_window.assert_called_once_with(200)

    assert await task is True
    client.set_scan_mode.assert_called_once_with(BleProxyMode.BLE_PROXY_MODE_PASSIVE)
