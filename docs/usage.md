(usage)=

# Usage

Assuming that you've followed the {ref}`installation steps <installation>`,
you're now ready to use this package.

The SLZB proxy is scan only, so its advertisements are registered with
`habluetooth` as **non-connectable**. That has a consequence worth stating up
front: `bleak.BleakScanner` talks to the local adapter and never consults
`habluetooth`, and `habluetooth.HaBleakScannerWrapper`'s bleak-compatible
surface (`discover()`, `discovered_devices`, `detection_callback`) reads the
_connectable_ history, which a scan-only proxy never populates. Read proxied
advertisements through one of:

| Read path                                            | Style     |
| ---------------------------------------------------- | --------- |
| `get_manager().async_discovered_service_info(False)` | poll      |
| `get_manager().async_last_service_info(addr, False)` | poll      |
| `HaBleakScannerWrapper.find_device_by_address/name`  | poll      |
| `BluetoothManager._discover_service_info` (override) | streaming |

Example usage:

```python
from __future__ import annotations

import asyncio
import logging

import habluetooth

from bleak_smlight import SMLIGHTConnectionManager, SMLIGHTDeviceConfig

# An unlimited number of SLZB BLE proxies can be added here. ``source`` is a
# stable unique id for the proxy (typically its MAC address), ``host`` is the
# IP/hostname the UDP proxy server listens on, ``port`` is optional and
# defaults to 5050.
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
    await asyncio.sleep(5)  # Give time for advertisements to be received

    # Snapshot of everything seen so far. ``False`` means "the all-scanners
    # history"; passing ``True`` restricts it to connectable scanners and
    # would never return a proxy advertisement.
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
```

## Device configuration

Each proxy is described by a `SMLIGHTDeviceConfig`:

| Key      | Required | Description                                                              |
| -------- | -------- | ------------------------------------------------------------------------ |
| `source` | yes      | Stable unique id for the proxy, typically its MAC address.               |
| `name`   | yes      | Human-friendly adapter name shown by `habluetooth`.                      |
| `host`   | yes      | IP or hostname the UDP proxy server listens on.                          |
| `port`   | no       | UDP port of the proxy server; defaults to `SLZB_BLE_SERVER_PORT` (5050). |

`SMLIGHTConnectionManager.start()` returns once the scanner is registered and the
proxy client has been started; it does not block waiting for the device to
respond, because the underlying `pysmlight.BleProxyClient` retries in the
background. Call `start()` once per manager instance; a second call raises
`RuntimeError`. `stop()` is always safe to call, including before `start()`.

## Advanced: wiring `connect_scanner` directly

`SMLIGHTConnectionManager` is the recommended entry point: it builds the scanner,
registers it with `habluetooth`, starts the proxy client, and tears everything
down on `stop()`. Reach for `connect_scanner` only when you want to own the
scanner registration and proxy-client lifecycle yourself.

`connect_scanner(source, name, host, port=SLZB_BLE_SERVER_PORT)` builds a
`SMLIGHTScanner` plus a `pysmlight.BleProxyClient` wired to its advertisement
callback, and returns a `SMLIGHTClientData`. It leaves three jobs to the caller:

1. Call `data.scanner.async_setup()` to attach the scanner to the running loop.
2. Register the scanner with the host-side Bluetooth manager (and unregister it
   on teardown).
3. `await data.client.start()` to begin receiving advertisements, and
   `data.client.stop()` on teardown.

```python
import habluetooth

import bleak_smlight

# habluetooth registers its manager singleton inside ``async_setup()``; without
# this line ``get_manager()`` below raises ``RuntimeError``.
await habluetooth.BluetoothManager().async_setup()

data = bleak_smlight.connect_scanner(
    "AA:BB:CC:DD:EE:FF", "slzb-1", "10.0.0.5"
)
unsetup = data.scanner.async_setup()
unregister = habluetooth.get_manager().async_register_scanner(data.scanner)
await data.client.start()

# Later, on teardown:
data.client.stop()
unregister()
unsetup()
```
