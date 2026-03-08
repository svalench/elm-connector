"""
ELM327 Bluetooth Connector — Python-коннектор для OBD-II адаптеров ELM327.
Поиск устройств, идентификация чипа, установка соединения с подробным RX/TX логированием.
"""

__version__ = "0.1.0"

from elm_connector.scanner import scan_devices, DeviceInfo
from elm_connector.connection import SerialConnection
from elm_connector.elm327 import ELM327

__all__ = [
    "scan_devices",
    "DeviceInfo",
    "SerialConnection",
    "ELM327",
]
