"""
Управление serial-соединением с подробным RX/TX логированием в консоль.
"""

import logging
import re
from typing import Optional

import serial

try:
    from colorama import Fore, Style, init as colorama_init
    colorama_init()
    HAS_COLORAMA = True
except ImportError:
    HAS_COLORAMA = False
    Fore = Style = None  # type: ignore

logger = logging.getLogger(__name__)

# Промпт ELM327
ELM_PROMPT = b">"


def _tx_log(msg: str) -> None:
    """Логирование исходящих данных (TX) с выделением."""
    if HAS_COLORAMA and Fore:
        logger.debug("%sTX >>> %s%s", Fore.BLUE, repr(msg), Style.RESET_ALL)
    else:
        logger.debug("TX >>> %s", repr(msg))


def _rx_log(msg: str) -> None:
    """Логирование входящих данных (RX) с выделением."""
    if HAS_COLORAMA and Fore:
        logger.debug("%sRX <<< %s%s", Fore.GREEN, repr(msg), Style.RESET_ALL)
    else:
        logger.debug("RX <<< %s", repr(msg))


def _err_log(msg: str) -> None:
    """Логирование ошибок с выделением."""
    if HAS_COLORAMA and Fore:
        logger.error("%s%s%s", Fore.RED, msg, Style.RESET_ALL)
    else:
        logger.error("%s", msg)


class SerialConnection:
    """
    Обёртка над serial.Serial с подробным логированием TX/RX.
    """

    def __init__(
        self,
        port: str,
        baudrate: int = 38400,
        timeout: float = 1.0,
        write_timeout: float = 1.0,
    ):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.write_timeout = write_timeout
        self._serial: Optional[serial.Serial] = None

    def open(self) -> None:
        """Открыть соединение."""
        if self._serial and self._serial.is_open:
            return
        logger.info("Connecting to %s @ %d baud...", self.port, self.baudrate)
        self._serial = serial.Serial(
            port=self.port,
            baudrate=self.baudrate,
            timeout=self.timeout,
            write_timeout=self.write_timeout,
        )
        logger.info("Connected to %s", self.port)

    def close(self) -> None:
        """Закрыть соединение."""
        if self._serial and self._serial.is_open:
            self._serial.close()
            logger.info("Disconnected from %s", self.port)
        self._serial = None

    def is_open(self) -> bool:
        return self._serial is not None and self._serial.is_open

    def send(self, data: str) -> None:
        """Отправить строку с \\r, логировать TX."""
        if not self._serial or not self._serial.is_open:
            raise RuntimeError("Connection not open")
        raw = data if data.endswith("\r") else data + "\r"
        self._serial.write(raw.encode("ascii"))
        _tx_log(raw)

    def receive(self) -> str:
        """
        Читать данные до промпта '>'.
        Возвращает полный ответ (без промпта), логирует RX.
        """
        if not self._serial or not self._serial.is_open:
            raise RuntimeError("Connection not open")

        buffer: list[bytes] = []
        while True:
            chunk = self._serial.read(256)
            if not chunk:
                break
            buffer.append(chunk)
            if ELM_PROMPT in chunk:
                break
            if len(chunk) < 256:
                break

        raw = b"".join(buffer)
        text = raw.decode("ascii", errors="replace").strip()
        _rx_log(text)
        return text

    def command(self, cmd: str) -> str:
        """
        Отправить команду и получить ответ.
        Возвращает очищенный текст ответа (без промпта и лишних символов).
        """
        self.send(cmd)
        response = self.receive()
        # Убираем промпт, эхо команды, лишние пробелы
        cleaned = self._clean_response(response, cmd)
        return cleaned

    def _clean_response(self, response: str, sent_cmd: str) -> str:
        """Очистка ответа от эхо, промпта и лишних символов."""
        lines = response.replace("\r", "\n").split("\n")
        result_lines: list[str] = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            if line == ">":
                continue
            # Эхо: ELM327 может возвращать отправленную команду
            if line.upper() == sent_cmd.upper().strip():
                continue
            if line.startswith(">"):
                line = line[1:].strip()
            if line:
                result_lines.append(line)
        return "\n".join(result_lines)

    def __enter__(self) -> "SerialConnection":
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
