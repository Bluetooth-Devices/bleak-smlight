(usage)=

# Usage

Assuming that you've followed the {ref}`installation steps <installation>`,
you're now ready to use this package.

The SLZB proxy is scan only, so devices are discoverable through `bleak` but not
connectable.

Example usage with `bleak`:

```python
from __future__ import annotations

import asyncio
import logging

import habluetooth

from bleak_smlight import SMLIGHTConnectionManager, SMLIGHTDeviceConfig

CONNECTION_TIMEOUT = 5

# An unlimited number of SLZB BLE proxies can be added here. ``source`` is a
# stable unique id for the proxy (typically its MAC address), ``host`` is the
# IP/hostname the UDP proxy server listens on, ``port`` is optional and
# defaults to 5050.
SMLIGHT_DEVICES: list[SMLIGHTDeviceConfig] = [
    {"source": "AA:BB:CC:DD:EE:FF", "name": "slzb-1", "host": "10.0.0.5"},
    {"source": "AA:BB:CC:DD:EE:00", "name": "slzb-2", "host": "10.0.0.6"},
]


async def example_app() -> None:
    """Example application here."""
    import bleak

    await asyncio.sleep(5)  # Give time for advertisements to be received

    # Use bleak normally here
    devices = await bleak.BleakScanner.discover(return_adv=True)
    for d, a in devices.values():
        print()
        print(d)
        print("-" * len(str(d)))
        print(a)

    # Wait forever
    await asyncio.Event().wait()


async def run() -> None:
    """Run the main application."""
    managers = [SMLIGHTConnectionManager(device) for device in SMLIGHT_DEVICES]
    await habluetooth.BluetoothManager().async_setup()
    try:
        await asyncio.wait(
            [asyncio.create_task(manager.start()) for manager in managers],
            timeout=CONNECTION_TIMEOUT,
        )
        await example_app()
    finally:
        await asyncio.gather(*(manager.stop() for manager in managers))


logging.basicConfig(level=logging.DEBUG)
asyncio.run(run())
```

## Device configuration

Each proxy is described by a `SMLIGHTDeviceConfig`:

| Key      | Required | Description                                                            |
| -------- | -------- | --------------------------------------------------------------------- |
| `source` | yes      | Stable unique id for the proxy, typically its MAC address.            |
| `name`   | yes      | Human-friendly adapter name shown by `habluetooth`.                   |
| `host`   | yes      | IP or hostname the UDP proxy server listens on.                       |
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
