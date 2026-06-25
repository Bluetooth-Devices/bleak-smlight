"""Host-side Bleak backend for SMLIGHT SLZB BLE proxies."""

from .connect import SLZB_BLE_SERVER_PORT, SMLIGHTClientData, connect_scanner
from .connection_manager import SMLIGHTConnectionManager, SMLIGHTDeviceConfig

__version__ = "1.0.0"

__all__ = [
    "SLZB_BLE_SERVER_PORT",
    "SMLIGHTClientData",
    "SMLIGHTConnectionManager",
    "SMLIGHTDeviceConfig",
    "__version__",
    "connect_scanner",
]
