"""Host-side Bleak backend for SMLIGHT SLZB BLE proxies."""

from .backend.scanner import SMLIGHTScanner
from .connect import SLZB_BLE_SERVER_PORT, SMLIGHTClientData, connect_scanner
from .connection_manager import SMLIGHTConnectionManager, SMLIGHTDeviceConfig

__version__ = "1.1.1"

__all__ = [
    "SLZB_BLE_SERVER_PORT",
    "SMLIGHTClientData",
    "SMLIGHTConnectionManager",
    "SMLIGHTDeviceConfig",
    "SMLIGHTScanner",
    "__version__",
    "connect_scanner",
]
