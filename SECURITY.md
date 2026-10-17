# Security Policy

## Reporting a vulnerability

Please open a [GitHub issue](https://github.com/Bluetooth-Devices/bleak-smlight/issues)
or, for anything sensitive, use GitHub's
[private vulnerability reporting](https://github.com/Bluetooth-Devices/bleak-smlight/security/advisories/new).

## Known trust boundary: the SLZB proxy protocol is unauthenticated

`bleak-smlight` consumes advertisements relayed by a SMLIGHT SLZB-U BLE proxy
over UDP. That protocol has no authentication — anything on the same network
segment that can reach the proxy's port can inject advertisements or forge the
connection handshake, and `habluetooth`'s best-RSSI resolution means an
injected advertisement can override a real device's data. This is a property
of the wire protocol (implemented in
[`pysmlight`](https://github.com/smlight-tech/pysmlight)), not something this
library can mitigate on its own.

Treat the network the proxy is reachable from as a trust boundary — do not
expose it to networks you don't control. See the
[architecture doc's Security considerations](https://bleak-smlight.readthedocs.io/en/latest/architecture.html#security-considerations)
section and
[#24](https://github.com/Bluetooth-Devices/bleak-smlight/issues/24) for the
full writeup.
