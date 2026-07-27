# API reference

Auto-generated reference for the public surface of `bleak_smlight` — the names
exported from the top-level package. For how these pieces fit together, see [the
architecture overview](architecture.md); for task-oriented examples, see
[usage](usage.md).

Everything documented here is re-exported from `bleak_smlight` directly, so the
import you write in application code is, for example:

```python
from bleak_smlight import SMLIGHTConnectionManager, SMLIGHTDeviceConfig
```

## High-level entry point

`SMLIGHTConnectionManager` is the standalone, Home-Assistant-free way to drive a
SLZB BLE proxy: hand it a device config, `await start()`, and it owns the proxy
client and scanner registration for you.

```{eval-rst}
.. autoclass:: bleak_smlight.SMLIGHTConnectionManager
   :members:
   :undoc-members:

.. autoclass:: bleak_smlight.SMLIGHTDeviceConfig
   :members:
   :undoc-members:
```

## Scanner

`SMLIGHTScanner` is the `habluetooth` remote scanner fed by the proxy. You do
not construct it — `SMLIGHTConnectionManager` and `connect_scanner` do — but it
is the handle for runtime scan-mode control, reached via `manager.scanner` or
`SMLIGHTClientData.scanner`. See the "Scanning modes" section of
[usage](usage.md) for why `AUTO` has to come from the device config instead.

```{eval-rst}
.. autoclass:: bleak_smlight.SMLIGHTScanner
   :members: set_client, async_set_scanning_mode, async_request_active_window
```

## Low-level escape hatch

`connect_scanner` is for advanced callers that manage their own scanner
registration and proxy-client lifecycle. It builds a `SMLIGHTScanner` plus a
`pysmlight.BleProxyClient` and returns the assembled `SMLIGHTClientData`, but
leaves scanner setup, manager registration, and client start/stop up to you.
Read the docstring carefully before reaching for it.

```{eval-rst}
.. autofunction:: bleak_smlight.connect_scanner

.. autoclass:: bleak_smlight.SMLIGHTClientData
   :members:
   :undoc-members:

.. autodata:: bleak_smlight.SLZB_BLE_SERVER_PORT
```
