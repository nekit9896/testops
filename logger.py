import json
import logging

import structlog
from flask import has_request_context, request
from structlog.processors import CallsiteParameter

from constants import LOG_FILE_NAME


class JSONFileProcessor:
    """
    Класс для сохранения логов json файл
    """

    def __init__(self, file_path: str, max_log_lines: int = 200):
        self.file_path = file_path
        self.max_log_lines = max_log_lines

    def __call__(self, _, __, event_dict: dict) -> dict:
        try:
            with open(self.file_path, "r", encoding="utf-8") as file:
                logs = json.load(file)

        except (FileNotFoundError, json.JSONDecodeError):
            logs = []

        logs.append(event_dict)

        if len(logs) > self.max_log_lines:
            logs = logs[-self.max_log_lines :]  # noqa: E203

        with open(self.file_path, "w", encoding="utf-8") as file:
            json.dump(logs, file, ensure_ascii=False, indent=2)

        return event_dict


def add_request_data(_, __, event_dict: dict) -> dict:
    """Добавляет request-данные."""
    if has_request_context():
        event_dict["method"] = request.method
        event_dict["url"] = request.url
        event_dict["ip"] = request.remote_addr

    return event_dict


_logger_configured = False


def setup_logger(file_path: str) -> None:
    """
    Настраивает structlog с JSON-форматированием.
    Вызывается один раз при импорте модуля.
    """
    global _logger_configured
    if _logger_configured:
        return
    _logger_configured = True

    structlog.configure(
        processors=[
            # Очень важно соблюдать последовательность процессоров
            structlog.processors.TimeStamper(fmt="iso"),  # Добавляет метку времени
            structlog.processors.StackInfoRenderer(),  # Добавляет информацию о стеке вызовов
            structlog.processors.CallsiteParameterAdder(
                {CallsiteParameter.FILENAME, CallsiteParameter.FUNC_NAME}
            ),
            structlog.processors.add_log_level,  # Добавляет уровень логирования в сообщение
            structlog.processors.dict_tracebacks,  # Преобразует сообщения tracebacks в словарь
            structlog.dev.set_exc_info,  # Добавляет информацию исключения
            structlog.processors.format_exc_info,  # Форматирует информацию об исключении
            add_request_data,  # Добавляет данные из request
            JSONFileProcessor(file_path),  # Сохраняет в json файл
            structlog.processors.JSONRenderer(
                ensure_ascii=False
            ),  # Вывод в JSON, отображение кириллицы
        ],
        context_class=dict,
        # PrintLoggerFactory выводит напрямую без дублирования через stdlib logging
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def init_logger() -> structlog.getLogger:
    """
    Инициализирует логгер.
    """
    return structlog.get_logger()


# Включает конфигурацию логера
setup_logger(LOG_FILE_NAME)

# Останавливает дефолтный логгер
logging.getLogger("werkzeug").disabled = True
