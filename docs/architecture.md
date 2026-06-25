(architecture)=

# Architecture

This page explains what `bleak-smlight` does, where the SMLIGHT BLE proxy is
implemented, and how the pieces fit together. If you only want to use the
library, see {ref}`usage`.

## What this library is, and what it is not

`bleak-smlight` is the glue layer that lets a Python application receive
Bluetooth Low Energy (BLE) advertisements from a **SMLIGHT SLZB-U BLE proxy**, an
ESP32-S3 running SLZB-OS. It does **not** implement the proxy itself. The proxy
is firmware on the device that exposes a small UDP server; this library is the
host-side client that consumes that server's advertisement stream.

The proxy is **scan only**. It relays raw BLE advertisements but has no
GATT/active-connection support, so this library registers a non-connectable
scanner and provides no Bleak _client_.

The split is:

| Layer                                            | Where it lives               | Repository                                                                        |
| ------------------------------------------------ | ---------------------------- | --------------------------------------------------------------------------------- |
| SLZB firmware (UDP BLE proxy server)             | On the SLZB-U device (ESP32) | SLZB-OS                                                                           |
| Python UDP client for the proxy                  | Host (your app)              | [smlight-tech/pysmlight](https://github.com/smlight-tech/pysmlight)               |
| `bleak`-compatible scanner on top of `pysmlight` | Host (your app)              | **this repo**                                                                     |
| Remote-scanner bookkeeping primitives            | Host (your app)              | [Bluetooth-Devices/habluetooth](https://github.com/Bluetooth-Devices/habluetooth) |
| Standard BLE scanner API consumed by user code   | Host (your app)              | [hbldh/bleak](https://github.com/hbldh/bleak)                                     |

So when you call `bleak.BleakScanner.discover(...)` in an app that has set up a
`SMLIGHTConnectionManager`, what really happens is:

1. The SLZB device scans for BLE advertisements over the air.
2. The proxy server forwards each advertisement to your host over Wi-Fi via UDP.
3. `pysmlight.BleProxyClient` parses the UDP packet and invokes its callback with
   the device MAC, RSSI, address type, and raw advertisement bytes.
4. `bleak-smlight`'s `SMLIGHTScanner._handle_raw_advertisement` forwards those
   values into `habluetooth`.
5. `bleak`'s discovery code sees those advertisements as if they had been seen by
   a local adapter.

There is no reverse path: the proxy cannot open GATT connections, so devices are
discoverable but not connectable.

## Where the proxy is implemented

Short answer: **not here.** The BLE proxy is part of the SLZB-OS firmware that
runs on the SLZB-U hardware. It exposes a UDP server (default port `5050`) that
streams advertisements to a host. The wire protocol and the host-side client
(`BleProxyClient`) live in
[pysmlight](https://github.com/smlight-tech/pysmlight).

What this repository contains:

- `src/bleak_smlight/connection_manager.py` — `SMLIGHTConnectionManager`, the
  convenience wrapper that builds a scanner, registers it with `habluetooth`,
  and starts the `BleProxyClient`.
- `src/bleak_smlight/connect.py` — `connect_scanner()`, which builds a
  `SMLIGHTScanner` plus a `pysmlight.BleProxyClient` wired to its advertisement
  callback, and returns them as a `SMLIGHTClientData`.
- `src/bleak_smlight/backend/scanner.py` — `SMLIGHTScanner`, a remote scanner
  that feeds advertisements received from the proxy into `habluetooth`.

## Connection lifecycle and retries

`BleProxyClient` owns its own connect/retry loop. `start()` returns immediately
after kicking off a background task that pings the proxy, waits for an ACK, and
retries with exponential backoff if the device is unreachable. Because of this,
`SMLIGHTConnectionManager.start()` does not block on the first successful
contact; the scanner is registered up front and begins reporting advertisements
as soon as packets arrive.

`stop()` tears down in order: it stops the proxy client (which sends a disconnect
packet and closes the UDP socket), unregisters the scanner from `habluetooth`,
and runs the scanner's own teardown callback.

## Who can use it

The library has no Home Assistant dependency. It is plain Python, built on
`asyncio`, and works in any host environment that can reach the SLZB device over
UDP and run `bleak` and `habluetooth`. The practical entry point is
`SMLIGHTConnectionManager` plus a list of `SMLIGHTDeviceConfig` entries, as shown
in {ref}`usage`.

## See also

- `pysmlight` (the UDP proxy client this library sits on top of):
  <https://github.com/smlight-tech/pysmlight>
- `habluetooth` (remote-scanner primitives):
  <https://github.com/Bluetooth-Devices/habluetooth>
