"""
Протокол ELM327: AT-команды, идентификация чипа, подключение к авто.
"""

import logging
from typing import Any, Optional

from elm_connector.connection import SerialConnection

logger = logging.getLogger(__name__)


class ELM327Error(Exception):
    """Ошибка протокола ELM327."""

    pass


class ELM327:
    """
    Протокол ELM327 — работа с OBD-II адаптером.
    """

    def __init__(self, connection: SerialConnection):
        self.conn = connection

    def reset(self) -> str:
        """Сброс адаптера (ATZ)."""
        return self.conn.command("ATZ")

    def get_chip_info(self) -> dict[str, Any]:
        """
        Собрать техническую информацию о чипе через AT-команды.
        Возвращает словарь с полями chip_id, description, identifier, voltage и т.д.
        """
        info: dict[str, Any] = {}

        commands = [
            ("ATI", "chip_id"),
            ("AT@1", "description"),
            ("AT@2", "identifier"),
            ("ATRV", "voltage"),
            ("ATDP", "protocol"),
            ("ATDPN", "protocol_number"),
            ("ATE0", "echo_off"),
            ("ATH1", "headers_on"),
            ("ATAL", "allow_long"),
            ("ATSP0", "auto_protocol"),
        ]

        for cmd, key in commands:
            try:
                resp = self.conn.command(cmd)
                # Иногда ответ содержит несколько строк, берём первую значимую
                lines = [l.strip() for l in resp.split("\n") if l.strip()]
                value = lines[0] if lines else resp
                info[key] = value
            except Exception as e:
                logger.debug("AT command %s failed: %s", cmd, e)
                info[key] = None

        return info

    def connect_to_vehicle(self) -> str:
        """
        Попытка подключения к автомобилю (запрос поддерживаемых PIDs).
        Команда 0100 — Mode 01, PID 00.
        """
        return self.conn.command("0100")

    def send_raw(self, cmd: str) -> str:
        """Отправить произвольную команду (AT или OBD) и вернуть ответ."""
        return self.conn.command(cmd)


def format_chip_info(info: dict[str, Any]) -> str:
    """Форматирование информации о чипе для вывода в лог."""
    lines: list[str] = []
    labels = {
        "chip_id": "Chip ID",
        "description": "Description",
        "identifier": "Identifier",
        "voltage": "Voltage",
        "protocol": "Protocol",
        "protocol_number": "Protocol Number",
    }
    for key, label in labels.items():
        val = info.get(key)
        if val is not None:
            lines.append(f"  {label}: {val}")
    return "\n".join(lines) if lines else "  (no info)"
