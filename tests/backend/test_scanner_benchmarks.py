"""Benchmarks for ``SMLIGHTScanner._handle_raw_advertisement``."""

from __future__ import annotations

import pytest
from pytest_codspeed import BenchmarkFixture

from bleak_smlight.backend.scanner import SMLIGHTScanner

PROXY_SOURCE = "AA:BB:CC:DD:EE:FF"
PROXY_NAME = "slzb-proxy"

# (device_mac, rssi, address_type, raw_data) as delivered by BleProxyClient.
SMALL_BATCH: list[tuple[str, int, int, bytes]] = [
    (
        "EC:81:CC:F5:75:0C",
        -96,
        1,
        bytes.fromhex("020104030307fe18ff9705060016702500ca00000800000000000000020a00"),
    ),
    (
        "F3:0F:E7:17:8D:E2",
        -88,
        1,
        bytes.fromhex(
            "02011a1bff7500420401016fe08d17e70ff3e28d17e70ff22800000000000000"
        ),
    ),
]

REAL_BATCH: list[tuple[str, int, int, bytes]] = [
    (
        "60:55:F9:00:1A:20",
        -71,
        1,
        bytes.fromhex("02011a020a0c0bff4c001006421dd63f4f78"),
    ),
    ("77:13:1B:58:13:08", -66, 1, bytes.fromhex("0201050716feff0900ff10")),
    (
        "EC:81:CC:F5:75:0C",
        -87,
        1,
        bytes.fromhex("020104030307fe14ffa705060012702500ca00000800000000000000020a00"),
    ),
    ("4C:4F:4F:6B:45:1B", -84, 1, bytes.fromhex("02011a17ff4c0009081333c0a86b451b")),
]


@pytest.mark.parametrize(
    ("batch", "label"),
    [(SMALL_BATCH, "small"), (REAL_BATCH, "real")],
)
def test_handle_raw_advertisement(
    benchmark: BenchmarkFixture,
    batch: list[tuple[str, int, int, bytes]],
    label: str,
) -> None:
    """Benchmark forwarding a batch of advertisements 1000 times."""
    scanner = SMLIGHTScanner(PROXY_SOURCE, PROXY_NAME, None, False)

    @benchmark
    def _benchmark() -> None:
        for _ in range(1000):
            for mac, rssi, address_type, raw in batch:
                scanner._handle_raw_advertisement(mac, rssi, address_type, raw)
