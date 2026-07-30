"""
Integration tests against habluetooth's real auto-scan scheduler.

Every other test in this suite mocks habluetooth away, so a change in how the
scheduler binds scanners or dispatches windows passes CI untouched. These tests
drive the real :class:`habluetooth.BluetoothManager` — scheduler included — and
observe the effect on the wire, using a real ``pysmlight.BleProxyClient`` over
a recording transport. That locks the full
``habluetooth scheduler -> SMLIGHTScanner -> pysmlight -> UDP`` contract, the
mirror image of ``test_scanner_wire.py``'s inbound direction.
"""

from __future__ import annotations

import struct
from collections.abc import Awaitable, Callable, Iterator
from typing import Any

import pytest
from bleak_retry_connector import BleakSlotManager
from bluetooth_adapters import get_adapters
from habluetooth import (
    BluetoothManager,
    BluetoothScanningMode,
    get_manager,
    set_manager,
)
from pysmlight import BleProxyClient, BleProxyProtocol
from pysmlight.const import BleProxyMode, ProxyAction

from bleak_smlight.backend.scanner import SMLIGHTScanner, _proxy_ready

from .conftest import PROXY_NAME, PROXY_SOURCE

# habluetooth clamps every window to at least AUTO_WINDOW_MIN_DURATION (5s),
# so a shorter request cannot be used to keep the test quick.
SWEEP_DURATION = 5.0

# The on-demand bus-wide sweep is the only public API that opens a window
# without waiting out the scheduler's 60s minimum scan interval. It arrived in
# habluetooth 6.7.0, above the >=6.4.0 floor this package declares, so the
# test that needs it skips rather than forcing a newer floor on a runtime path
# that works fine without it. Resolved here rather than called by name so the
# type check does not depend on which habluetooth happens to be installed.
_on_demand_sweep: Callable[[BluetoothManager, float], Awaitable[None]] | None = getattr(
    BluetoothManager, "async_request_active_scan", None
)


class RecordingTransport:
    """Minimal ``DatagramTransport`` stand-in that captures sent packets."""

    def __init__(self) -> None:
        self.sent: list[bytes] = []

    def sendto(self, packet: bytes, addr: Any = None) -> None:
        self.sent.append(packet)

    def close(self) -> None:
        pass


def _action(packet: bytes) -> ProxyAction:
    """Return the proxy action a sent packet carries."""
    return ProxyAction(packet[1])


def _ack(client: BleProxyClient) -> None:
    """
    Complete ``client``'s handshake the way the firmware really does.

    Feeds a genuine two-byte ACK datagram through ``pysmlight``'s own
    ``BleProxyProtocol`` decoder into the client's ACK handler, rather than
    setting the readiness flag directly. ``_proxy_ready`` reads a private
    ``pysmlight`` attribute because ``BleProxyClient`` exposes no public
    connected signal; routing every test through the real decode path means a
    rename there breaks these tests loudly on the dependency bump instead of
    reaching a consumer as an ``AttributeError``.
    """
    protocol = BleProxyProtocol(client.callback, client._on_ack)
    protocol.datagram_received(bytes([0, ProxyAction.ACK]), ("10.0.0.5", 5050))


@pytest.fixture
def auto_manager() -> Iterator[BluetoothManager]:
    """
    A real manager, installed globally, whose scheduler the tests drive.

    The session-wide manager fixture never calls ``async_setup()``, which is
    what binds the auto-scan scheduler to the loop; without it no worker is
    ever spawned. The previous manager is reinstalled on teardown so the rest
    of the suite keeps the one it registers against.
    """
    previous = get_manager()
    manager = BluetoothManager(get_adapters(), BleakSlotManager())
    set_manager(manager)
    yield manager
    manager.async_stop()
    set_manager(previous)


@pytest.fixture
def armed_scanner() -> tuple[SMLIGHTScanner, RecordingTransport]:
    """An AUTO-seeded scanner wired to a real client over a fake transport."""
    scanner = SMLIGHTScanner(
        PROXY_SOURCE,
        PROXY_NAME,
        None,
        False,
        requested_mode=BluetoothScanningMode.AUTO,
    )
    client = BleProxyClient(
        esp32_ip="10.0.0.5",
        callback=scanner._handle_raw_advertisement,
        esp32_port=5050,
    )
    transport = RecordingTransport()
    client.transport = transport  # type: ignore[assignment]
    # The scanner refuses windows until the proxy has answered, so drive the
    # real PING/ACK decode rather than poking the readiness flag.
    _ack(client)
    scanner.set_client(client)
    return scanner, transport


@pytest.mark.parametrize(
    ("mode", "expect_worker"),
    [(BluetoothScanningMode.AUTO, True), (None, False)],
)
@pytest.mark.asyncio
async def test_auto_worker_binds_only_when_seeded_before_registration(
    auto_manager: BluetoothManager,
    mode: BluetoothScanningMode | None,
    expect_worker: bool,
) -> None:
    """
    Only a scanner already reporting AUTO gets an auto-scan worker.

    ``AutoScanScheduler.add_scanner`` returns early unless the scanner
    reports AUTO at registration, and nothing re-binds a worker afterwards.
    That is why ``connect_scanner()`` takes ``mode`` instead of leaving the
    caller to select AUTO after ``start()`` — doing so pins the mode locally
    and never opens a single window. Assert it through the scheduler rather
    than trusting the docstring.
    """
    await auto_manager.async_setup()
    scanner = SMLIGHTScanner(PROXY_SOURCE, PROXY_NAME, None, False, requested_mode=mode)
    unsetup = scanner.async_setup()
    unregister = auto_manager.async_register_scanner(scanner)
    try:
        workers = auto_manager._auto_scheduler._workers
        assert (PROXY_SOURCE in workers) is expect_worker
    finally:
        unregister()
        unsetup()


@pytest.mark.skipif(
    _on_demand_sweep is None,
    reason="needs habluetooth >=6.7.0 for async_request_active_scan",
)
@pytest.mark.asyncio
async def test_scheduler_window_reaches_the_firmware(
    auto_manager: BluetoothManager,
    armed_scanner: tuple[SMLIGHTScanner, RecordingTransport],
) -> None:
    """
    A scheduler-driven window arms the proxy, then restores it.

    Drives ``manager.async_request_active_scan()`` — the real dispatch path —
    and checks what actually left the socket: pysmlight's own encoding of
    ``REQ_ACTIVE_WINDOW`` carrying the duration in milliseconds, followed by
    the firmware going back to PASSIVE (AUTO's firmware equivalent) once the
    window closes itself.
    """
    assert _on_demand_sweep is not None
    await auto_manager.async_setup()
    scanner, transport = armed_scanner
    unsetup = scanner.async_setup()
    unregister = auto_manager.async_register_scanner(scanner)
    try:
        await _on_demand_sweep(auto_manager, SWEEP_DURATION)
    finally:
        unregister()
        unsetup()

    assert [_action(packet) for packet in transport.sent] == [
        ProxyAction.REQ_ACTIVE_WINDOW,
        ProxyAction.SET_SCAN_MODE,
    ]
    assert struct.unpack("<BBH", transport.sent[0]) == (
        0,
        ProxyAction.REQ_ACTIVE_WINDOW,
        int(SWEEP_DURATION * 1000),
    )
    assert transport.sent[1][2] == BleProxyMode.BLE_PROXY_MODE_PASSIVE
    assert scanner.current_mode is BluetoothScanningMode.AUTO


@pytest.mark.asyncio
async def test_readiness_gate_follows_a_real_ack_datagram() -> None:
    """
    The handshake gate opens on a decoded ACK, not on a poked flag.

    Every other test stands in for the handshake by setting ``pysmlight``'s
    private readiness flag, which keeps passing even if that attribute is
    renamed or dropped — leaving the gate to fail as an ``AttributeError`` in
    a consumer. This drives the whole chain instead: a real ACK datagram
    through ``pysmlight``'s decoder, and the window request that gate governs.
    """
    scanner = SMLIGHTScanner(
        PROXY_SOURCE,
        PROXY_NAME,
        None,
        False,
        requested_mode=BluetoothScanningMode.AUTO,
    )
    client = BleProxyClient(
        esp32_ip="10.0.0.5",
        callback=scanner._handle_raw_advertisement,
        esp32_port=5050,
    )
    transport = RecordingTransport()
    client.transport = transport  # type: ignore[assignment]
    scanner.set_client(client)

    # A client whose transport is bound but whose proxy has never answered is
    # exactly the state ``BleProxyClient.start()`` leaves behind.
    assert _proxy_ready(client) is False
    assert await scanner.async_request_active_window(0.01) is False
    assert transport.sent == []

    _ack(client)

    assert _proxy_ready(client) is True
    assert await scanner.async_request_active_window(0.01) is True
    assert [_action(packet) for packet in transport.sent] == [
        ProxyAction.REQ_ACTIVE_WINDOW,
        ProxyAction.SET_SCAN_MODE,
    ]
    assert struct.unpack("<BBH", transport.sent[0]) == (
        0,
        ProxyAction.REQ_ACTIVE_WINDOW,
        10,
    )


@pytest.mark.parametrize("duration", [0.0, -1.0, 0.0004, float("nan"), float("inf")])
@pytest.mark.asyncio
async def test_unusable_durations_cost_no_packets(
    armed_scanner: tuple[SMLIGHTScanner, RecordingTransport],
    duration: float,
) -> None:
    """
    A window the firmware cannot hold is refused before anything is sent.

    The proxy timeout is whole milliseconds, so a sub-millisecond duration
    truncates to a 0 ms window: arming it would spend an arm/restore packet
    pair on a window that is over before it opens. Non-finite durations would
    raise out of the clamp.
    """
    scanner, transport = armed_scanner

    assert await scanner.async_request_active_window(duration) is False
    assert transport.sent == []
