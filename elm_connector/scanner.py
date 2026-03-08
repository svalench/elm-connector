"""
Поиск ELM327 устройств через serial ports, BLE и macOS system_profiler.
"""

import glob
import logging
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import List

import serial.tools.list_ports

logger = logging.getLogger(__name__)

# Ключевые слова для фильтрации serial-портов
SERIAL_KEYWORDS = ("obd", "elm", "obdii", "obd2", "spp", "vlink", "scanner")

# Исключения: служебные порты, не относящиеся к OBD
SERIAL_EXCLUDE = ("bluetooth-incoming-port", "incoming-port")

# Ключевые слова для фильтрации BLE-устройств
BLE_KEYWORDS = ("obd", "elm", "obdii", "obd2", "obd-ii", "vlink", "bluetooth")


@dataclass
class DeviceInfo:
    """Информация о найденном устройстве."""
    path: str  # путь/адрес для подключения
    name: str
    device_type: str  # "serial", "ble", "paired"
    description: str = ""

    def __str__(self) -> str:
        desc = f" ({self.description})" if self.description else ""
        return f"{self.path} — {self.name}{desc} [{self.device_type}]"


def _scan_serial_ports() -> List[DeviceInfo]:
    """Поиск serial-портов, похожих на ELM327 (Bluetooth SPP, USB)."""
    devices: List[DeviceInfo] = []
    try:
        for port in serial.tools.list_ports.comports():
            name = (port.description or "").lower()
            hwid = (port.hwid or "").lower()
            combined = f"{name} {hwid}".lower()

            if any(ex in combined for ex in SERIAL_EXCLUDE):
                continue
            if any(kw in combined for kw in SERIAL_KEYWORDS):
                devices.append(DeviceInfo(
                    path=port.device,
                    name=port.description or port.device,
                    device_type="serial",
                    description=port.hwid or "",
                ))
    except Exception as e:
        logger.debug("Serial scan error: %s", e)
    return devices


def _scan_ble() -> List[DeviceInfo]:
    """Поиск BLE-устройств, похожих на ELM327."""
    devices: List[DeviceInfo] = []
    try:
        import asyncio
        from bleak import BleakScanner

        async def discover():
            return await BleakScanner.discover(timeout=5.0)

        found = asyncio.run(discover())

        for d in found:
            name = (d.name or "").lower()
            if any(kw in name for kw in BLE_KEYWORDS):
                devices.append(DeviceInfo(
                    path=d.address,
                    name=d.name or d.address,
                    device_type="ble",
                    description="BLE device",
                ))
    except ImportError:
        logger.debug("BLE scan skipped: bleak not installed")
    except Exception as e:
        err_msg = str(e).lower()
        if "windows" in err_msg or "property is not available" in err_msg or "unsupported" in err_msg:
            logger.debug("BLE scan skipped: not supported on this system (ELM327 often uses Bluetooth Classic)")
        else:
            logger.debug("BLE scan error: %s", e)
    return devices


def _scan_macos_bluetooth_paired() -> List[DeviceInfo]:
    """Получение спаренных Bluetooth Classic устройств через system_profiler (macOS)."""
    devices: List[DeviceInfo] = []
    if sys.platform != "darwin":
        return devices
    try:
        result = subprocess.run(
            ["system_profiler", "SPBluetoothDataType"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            return devices

        text = result.stdout
        # Ищем устройства по паттерну (имя и т.д.)
        for kw in SERIAL_KEYWORDS:
            if kw in text.lower():
                # Извлекаем имена устройств из вывода
                for line in text.splitlines():
                    line_lower = line.lower()
                    if kw in line_lower and ("name:" in line_lower or "device" in line_lower):
                        # Упрощённый парсинг: берём строки с именами
                        m = re.search(r"([A-Za-z0-9_\-]+OBD[A-Za-z0-9_\-]*|[A-Za-z0-9_\-]+ELM[A-Za-z0-9_\-]*)", line, re.I)
                        if m:
                            name = m.group(1).strip()
                            devices.append(DeviceInfo(
                                path=name,  # для paired используем имя, порт — /dev/tty.*
                                name=name,
                                device_type="paired",
                                description="Bluetooth paired (check /dev/tty.* for serial)",
                            ))
                break
    except FileNotFoundError:
        logger.debug("system_profiler not found")
    except subprocess.TimeoutExpired:
        logger.debug("system_profiler timed out")
    except Exception as e:
        logger.debug("system_profiler error: %s", e)

    # Дополнительно ищем /dev/tty.* порты, которые могут быть BT SPP (macOS)
    try:
        for port in glob.glob("/dev/tty.*"):
            name = port.split("/")[-1].lower()
            if any(ex in name for ex in SERIAL_EXCLUDE):
                continue
            if any(kw in name for kw in ("obd", "elm", "spp")):
                if not any(d.path == port for d in devices):
                    devices.append(DeviceInfo(
                        path=port,
                        name=port.split("/")[-1],
                        device_type="serial",
                        description="Bluetooth SPP",
                    ))
    except Exception:
        pass

    return devices


def scan_devices() -> List[DeviceInfo]:
    """
    Сканирование всех доступных способов поиска ELM327.
    Возвращает объединённый список без дубликатов по path.
    """
    all_devices: List[DeviceInfo] = []
    seen_paths: set = set()

    for scan_fn in [_scan_serial_ports, _scan_ble, _scan_macos_bluetooth_paired]:
        try:
            for dev in scan_fn():
                if dev.path and dev.path not in seen_paths:
                    seen_paths.add(dev.path)
                    all_devices.append(dev)
        except Exception as e:
            logger.debug("Scan function error: %s", e)

    return all_devices
