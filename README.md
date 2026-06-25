# bleak-smlight

<p align="center">
  <a href="https://github.com/bluetooth-devices/bleak-smlight/actions/workflows/ci.yml?query=branch%3Amain">
    <img src="https://img.shields.io/github/actions/workflow/status/bluetooth-devices/bleak-smlight/ci.yml?branch=main&label=CI&logo=github&style=flat-square" alt="CI Status" >
  </a>
  <a href="https://bleak-smlight.readthedocs.io">
    <img src="https://img.shields.io/readthedocs/bleak-smlight.svg?logo=read-the-docs&logoColor=fff&style=flat-square" alt="Documentation Status">
  </a>
  <a href="https://codecov.io/gh/bluetooth-devices/bleak-smlight">
    <img src="https://img.shields.io/codecov/c/github/bluetooth-devices/bleak-smlight.svg?logo=codecov&logoColor=fff&style=flat-square" alt="Test coverage percentage">
  </a>
  <a href="https://codspeed.io/Bluetooth-Devices/bleak-smlight"><img src="https://img.shields.io/endpoint?url=https://codspeed.io/badge.json" alt="CodSpeed Badge"/></a>
</p>
<p align="center">
  <a href="https://python-poetry.org/">
    <img src="https://img.shields.io/badge/packaging-poetry-299bd7?style=flat-square&logo=data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAA4AAAASCAYAAABrXO8xAAAACXBIWXMAAAsTAAALEwEAmpwYAAAAAXNSR0IArs4c6QAAAARnQU1BAACxjwv8YQUAAAJJSURBVHgBfZLPa1NBEMe/s7tNXoxW1KJQKaUHkXhQvHgW6UHQQ09CBS/6V3hKc/AP8CqCrUcpmop3Cx48eDB4yEECjVQrlZb80CRN8t6OM/teagVxYZi38+Yz853dJbzoMV3MM8cJUcLMSUKIE8AzQ2PieZzFxEJOHMOgMQQ+dUgSAckNXhapU/NMhDSWLs1B24A8sO1xrN4NECkcAC9ASkiIJc6k5TRiUDPhnyMMdhKc+Zx19l6SgyeW76BEONY9exVQMzKExGKwwPsCzza7KGSSWRWEQhyEaDXp6ZHEr416ygbiKYOd7TEWvvcQIeusHYMJGhTwF9y7sGnSwaWyFAiyoxzqW0PM/RjghPxF2pWReAowTEXnDh0xgcLs8l2YQmOrj3N7ByiqEoH0cARs4u78WgAVkoEDIDoOi3AkcLOHU60RIg5wC4ZuTC7FaHKQm8Hq1fQuSOBvX/sodmNJSB5geaF5CPIkUeecdMxieoRO5jz9bheL6/tXjrwCyX/UYBUcjCaWHljx1xiX6z9xEjkYAzbGVnB8pvLmyXm9ep+W8CmsSHQQY77Zx1zboxAV0w7ybMhQmfqdmmw3nEp1I0Z+FGO6M8LZdoyZnuzzBdjISicKRnpxzI9fPb+0oYXsNdyi+d3h9bm9MWYHFtPeIZfLwzmFDKy1ai3p+PDls1Llz4yyFpferxjnyjJDSEy9CaCx5m2cJPerq6Xm34eTrZt3PqxYO1XOwDYZrFlH1fWnpU38Y9HRze3lj0vOujZcXKuuXm3jP+s3KbZVra7y2EAAAAAASUVORK5CYII=" alt="Poetry">
  </a>
  <a href="https://github.com/astral-sh/ruff">
    <img src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json&style=flat-square" alt="Ruff">
  </a>
  <a href="https://github.com/pre-commit/pre-commit">
    <img src="https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit&logoColor=white&style=flat-square" alt="pre-commit">
  </a>
</p>
<p align="center">
  <a href="https://pypi.org/project/bleak-smlight/">
    <img src="https://img.shields.io/pypi/v/bleak-smlight.svg?logo=python&logoColor=fff&style=flat-square" alt="PyPI Version">
  </a>
  <img src="https://img.shields.io/pypi/pyversions/bleak-smlight.svg?style=flat-square&logo=python&amp;logoColor=fff" alt="Supported Python versions">
  <img src="https://img.shields.io/pypi/l/bleak-smlight.svg?style=flat-square" alt="License">
</p>

---

**Documentation**: <a href="https://bleak-smlight.readthedocs.io" target="_blank">https://bleak-smlight.readthedocs.io </a>

**Source Code**: <a href="https://github.com/bluetooth-devices/bleak-smlight" target="_blank">https://github.com/bluetooth-devices/bleak-smlight </a>

---

A [Bleak](https://github.com/hbldh/bleak) backend that receives Bluetooth Low
Energy advertisements from a SMLIGHT SLZB BLE proxy. The proxy is scan only, so
this library registers a non connectable scanner with
[habluetooth](https://github.com/Bluetooth-Devices/habluetooth); it does not
support GATT connections. The UDP proxy protocol lives in
[pysmlight](https://github.com/smlight-tech/pysmlight), this library is the host
side glue that feeds advertisements into Bleak. See the [architecture
docs](https://bleak-smlight.readthedocs.io/en/latest/architecture.html) for how
the pieces fit together.

## Usage

```python
import asyncio

import habluetooth

from bleak_smlight import SMLIGHTConnectionManager, SMLIGHTDeviceConfig

DEVICES: list[SMLIGHTDeviceConfig] = [
    {"source": "AA:BB:CC:DD:EE:FF", "name": "slzb-proxy", "host": "10.0.0.5"},
]


async def main() -> None:
    await habluetooth.BluetoothManager().async_setup()
    managers = [SMLIGHTConnectionManager(d) for d in DEVICES]
    await asyncio.gather(*(m.start() for m in managers))
    try:
        await asyncio.Event().wait()  # advertisements now flow into Bleak
    finally:
        await asyncio.gather(*(m.stop() for m in managers))


asyncio.run(main())
```

## Installation

Install this via pip (or your favourite package manager):

`pip install bleak-smlight`

## Contributors ✨

Thanks goes to these wonderful people ([emoji key](https://allcontributors.org/docs/en/emoji-key)):

<!-- prettier-ignore-start -->
<!-- ALL-CONTRIBUTORS-LIST:START - Do not remove or modify this section -->
<!-- markdownlint-disable -->
<!-- markdownlint-enable -->
<!-- ALL-CONTRIBUTORS-LIST:END -->
<!-- prettier-ignore-end -->

This project follows the [all-contributors](https://github.com/all-contributors/all-contributors) specification. Contributions of any kind welcome!

## Credits

This package was created with
[Copier](https://copier.readthedocs.io/) and the
[browniebroke/pypackage-template](https://github.com/browniebroke/pypackage-template)
project template.
