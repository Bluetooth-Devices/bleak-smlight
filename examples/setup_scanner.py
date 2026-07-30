from __future__ import annotations

import asyncio
import logging

import habluetooth

from bleak_smlight import SMLIGHTConnectionManager, SMLIGHTDeviceConfig

# An unlimited number of SLZB BLE proxies can be added here. ``source`` is a
# stable unique id for the proxy (typically its MAC address), ``host`` is the
# IP/hostname the UDP proxy server listens on.
SMLIGHT_DEVICES: list[SMLIGHTDeviceConfig] = [
    {"source": "AA:BB:CC:DD:EE:FF", "name": "slzb-1", "host": "10.0.0.5"},
    {"source": "AA:BB:CC:DD:EE:00", "name": "slzb-2", "host": "10.0.0.6"},
]


class ProxyBluetoothManager(habluetooth.BluetoothManager):
    """Receive every proxied advertisement as it arrives."""

    def _discover_service_info(
        self, service_info: habluetooth.BluetoothServiceInfoBleak
    ) -> None:
        print(service_info.address, service_info.name, service_info.rssi)


async def example_app() -> None:
    """Example application here."""
    await asyncio.sleep(5)  # Give time for the scanner to find devices

    # The SLZB proxy is scan-only, so its advertisements are registered as
    # non-connectable. ``bleak.BleakScanner`` (local adapter) and
    # ``HaBleakScannerWrapper.discover()`` (connectable history) both miss
    # them; read the all-scanners history instead.
    for info in habluetooth.get_manager().async_discovered_service_info(False):
        print()
        print(info.device)
        print("-" * len(str(info.device)))
        print(info.advertisement)

    # Wait forever
    await asyncio.Event().wait()


async def run() -> None:
    """Run the main application."""
    managers = [SMLIGHTConnectionManager(device) for device in SMLIGHT_DEVICES]
    await ProxyBluetoothManager().async_setup()
    try:
        # start() does not block on the device (the proxy client retries in
        # the background), so gather them concurrently and let any real
        # registration error surface instead of being swallowed.
        await asyncio.gather(*(manager.start() for manager in managers))
        await example_app()
    finally:
        await asyncio.gather(*(manager.stop() for manager in managers))


logging.basicConfig(level=logging.DEBUG)
asyncio.run(run())
