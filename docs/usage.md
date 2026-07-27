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
| `mode`   | no       | `BluetoothScanningMode` to run in; defaults to the firmware's own mode.  |

`SMLIGHTConnectionManager.start()` returns once the scanner is registered and the
proxy client has been started; it does not block waiting for the device to
respond, because the underlying `pysmlight.BleProxyClient` retries in the
background. Call `start()` once per manager instance; a second call raises
`RuntimeError`. `stop()` is always safe to call, including before `start()`.

## Scanning modes

Without a `mode`, the proxy stays on its firmware default. Set one in the
config and `start()` applies it:

```python
from habluetooth import BluetoothScanningMode

manager = SMLIGHTConnectionManager(
    {
        "source": "AA:BB:CC:DD:EE:FF",
        "name": "slzb-06",
        "host": "10.0.0.42",
        "mode": BluetoothScanningMode.AUTO,
    }
)
await manager.start()
```

- `PASSIVE` — listen only; the proxy never sends scan requests.
- `ACTIVE` — the proxy requests scan responses continuously.
- `AUTO` — the firmware stays passive, and `habluetooth`'s scheduler asks for
  short active windows on demand via `async_request_active_window()`. The
  firmware returns to passive when a window times out.

**`AUTO` only works from the config.** `habluetooth` binds a scanner to its
auto-scan scheduler when the scanner is registered, and only if the scanner
already reports `AUTO` at that moment. Selecting `AUTO` later pins the mode
locally but no active window is ever requested.

To repin `PASSIVE`/`ACTIVE` while running, reach the scanner through
`manager.scanner` — the registered `SMLIGHTScanner` between `start()` and
`stop()`, and `None` outside that window:

```python
assert manager.scanner is not None
manager.scanner.async_set_scanning_mode(BluetoothScanningMode.ACTIVE)
```

Modes are tracked locally: the SLZB firmware acknowledges configuration
commands but does not push mode updates back, so the scanner reports the mode
this library last asked for.

The configured `mode` is sent to the firmware in the background rather than by
`start()` itself, which keeps `start()` non-blocking: the proxy client only
schedules its connect loop, so it has no socket to send on until that loop has
run. Repinning through `manager.scanner` sends immediately and is dropped if
the proxy is unreachable — the local pin still stands, so re-issue it if the
device was down.

## Advanced: wiring `connect_scanner` directly

`SMLIGHTConnectionManager` is the recommended entry point: it builds the scanner,
registers it with `habluetooth`, starts the proxy client, and tears everything
down on `stop()`. Reach for `connect_scanner` only when you want to own the
scanner registration and proxy-client lifecycle yourself.

`connect_scanner(source, name, host, port=SLZB_BLE_SERVER_PORT, mode=None)`
builds a `SMLIGHTScanner` plus a `pysmlight.BleProxyClient` wired to its
advertisement callback, and returns a `SMLIGHTClientData`. `mode` seeds the
scanner's requested mode — pass `AUTO` here if you want the scheduler, since
it is bound when you register the scanner. It leaves three jobs to the caller:

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
