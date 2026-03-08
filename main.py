#!/usr/bin/env python3
"""
ELM327 Bluetooth Connector — точка входа.
Поиск устройств, идентификация чипа, соединение с подробным RX/TX логированием.
"""

import logging
import sys
from typing import Optional

try:
    from colorama import Fore, Style, init as colorama_init

    colorama_init()
    HAS_COLORAMA = True
except ImportError:
    HAS_COLORAMA = False
    Fore = Style = None  # type: ignore

from elm_connector import ELM327, DeviceInfo, SerialConnection, scan_devices
from elm_connector.elm327 import format_chip_info


class ColoredFormatter(logging.Formatter):
    """Форматтер с цветовым выделением по уровню (если colorama доступна)."""

    LEVEL_COLORS = {
        logging.DEBUG: Fore.CYAN if HAS_COLORAMA and Fore else "",
        logging.INFO: Fore.WHITE if HAS_COLORAMA and Fore else "",
        logging.WARNING: Fore.YELLOW if HAS_COLORAMA and Fore else "",
        logging.ERROR: Fore.RED if HAS_COLORAMA and Fore else "",
    }

    def format(self, record: logging.LogRecord) -> str:
        msg = super().format(record)
        color = self.LEVEL_COLORS.get(record.levelno, "")
        reset = Style.RESET_ALL if HAS_COLORAMA and Style else ""
        if color:
            return f"{color}{msg}{reset}"
        return msg


def setup_logging(level: int = logging.DEBUG) -> None:
    """Настройка подробного логирования в консоль."""
    fmt = "[%(asctime)s.%(msecs)03d] [%(levelname)-7s] %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"
    formatter = ColoredFormatter(fmt, datefmt=datefmt)
    formatter.default_msec_format = "%s"

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("bleak").setLevel(logging.WARNING)


def print_banner() -> None:
    """Вывод баннера программы."""
    banner = """
╔══════════════════════════════════════════════════════════════╗
║           ELM327 Bluetooth Connector                         ║
║  Поиск • Идентификация чипа • Соединение • RX/TX лог          ║
╚══════════════════════════════════════════════════════════════╝
"""
    print(banner)


def select_device(devices: list[DeviceInfo]) -> Optional[DeviceInfo]:
    """Выбор устройства: автоматически если одно, иначе интерактивный ввод."""
    if not devices:
        return None
    if len(devices) == 1:
        return devices[0]

    print("\nВыберите устройство:")
    for i, dev in enumerate(devices, 1):
        print(f"  {i}. {dev}")

    while True:
        try:
            choice = input("\nВведите номер (1–{}): ".format(len(devices))).strip()
            idx = int(choice)
            if 1 <= idx <= len(devices):
                return devices[idx - 1]
        except (ValueError, EOFError):
            pass
        print("Неверный выбор, повторите.")


def interactive_mode(elm: ELM327) -> None:
    """Интерактивный режим: ввод AT-команд вручную."""
    logger = logging.getLogger(__name__)
    print("\n--- Интерактивный режим ---")
    print("Вводите AT-команды или OBD PID (например ATZ, 0100). Пустая строка или 'quit' — выход.")
    print("-" * 40)

    while True:
        try:
            cmd = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nВыход.")
            break

        if not cmd or cmd.lower() in ("quit", "exit", "q"):
            print("Выход.")
            break

        try:
            resp = elm.send_raw(cmd)
            if resp:
                print(resp)
        except Exception as e:
            logger.error("Ошибка: %s", e)
            print(f"Ошибка: {e}")


def main() -> int:
    """Основная логика: сканирование → выбор → подключение → идентификация → интерактив."""
    setup_logging()
    logger = logging.getLogger(__name__)

    print_banner()

    # Этап 1: Сканирование
    logger.info("Scanning for ELM327 devices...")
    devices = scan_devices()

    if not devices:
        logger.warning("No ELM327 devices found.")
        logger.info("Ensure device is paired (macOS: System Settings → Bluetooth).")
        logger.info("For serial: check /dev/tty.* after pairing.")
        return 1

    logger.info("Found %d device(s):", len(devices))
    for dev in devices:
        logger.info("  • %s", dev)

    # Этап 2: Выбор устройства
    device = select_device(devices)
    if not device:
        return 1

    # Для BLE-устройств нужен другой путь подключения (ble-serial и т.п.)
    # Сейчас поддерживаем только serial-порты
    if device.device_type == "ble":
        logger.warning(
            "BLE devices require additional setup (e.g. ble-serial). "
            "Use a serial port for direct connection."
        )
        return 1

    if device.device_type == "paired":
        # paired хранит имя, нужно найти реальный порт
        port_candidates = [d for d in devices if d.device_type == "serial" and device.name.lower() in d.path.lower()]
        if port_candidates:
            device = port_candidates[0]
        else:
            logger.warning(
                "Paired device '%s' — pair first, then check /dev/tty.* for the serial port.",
                device.name,
            )
            return 1

    port_path = device.path
    logger.info("Using device: %s", port_path)

    # Этап 3: Подключение
    try:
        conn = SerialConnection(port=port_path, baudrate=38400)
        conn.open()
    except Exception as e:
        logger.error("Failed to connect: %s", e)
        return 1

    try:
        elm = ELM327(conn)

        # Этап 4: Идентификация чипа
        logger.info("Resetting adapter (ATZ)...")
        reset_resp = elm.reset()
        if reset_resp:
            logger.info("Reset response: %s", reset_resp.split("\n")[0] if "\n" in reset_resp else reset_resp)

        logger.info("Fetching chip info...")
        info = elm.get_chip_info()
        logger.info("Chip info:\n%s", format_chip_info(info))

        # Этап 5: Подключение к авто
        logger.info("Connecting to vehicle (0100)...")
        try:
            vehicle_resp = elm.connect_to_vehicle()
            logger.info("Vehicle response: %s", vehicle_resp[:200] if len(vehicle_resp) > 200 else vehicle_resp)
        except Exception as e:
            logger.warning("Vehicle connection failed (car may be off): %s", e)

        # Этап 6: Интерактивный режим
        interactive_mode(elm)

    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
