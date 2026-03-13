"""
Модуль настройки структурированного логирования (structlog).

Принципы:
- Вывод в stdout в формате JSON (для Docker logs / систем сбора логов).
- Опциональная запись в файл через RotatingFileHandler (append-only, без read-modify-write).
- Богатый контекст: timestamp, level, callsite (файл, функция, строка), данные HTTP-запроса, отформатированный traceback.
"""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from typing import Any

import structlog
from flask import has_request_context, request
from structlog.processors import CallsiteParameter

from constants import LOG_DIR, LOG_FILE_NAME, LOG_LEVEL, LOG_MAX_BYTES, LOG_BACKUP_COUNT


# ---------------------------------------------------
#  Процессор: добавление данных HTTP-запроса (Flask)
# ---------------------------------------------------
def add_request_context(
    _logger: Any, _method: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """
    Добавляет в лог-запись метод, URL, IP и user-agent текущего Flask-запроса.
    """
    if has_request_context():
        event_dict["http_method"] = request.method
        event_dict["http_url"] = request.url
        event_dict["http_ip"] = request.remote_addr
        user_agent = request.headers.get("User-Agent", "")
        if user_agent:
            event_dict["http_user_agent"] = user_agent[:500]
    return event_dict


# --------------------------------------------------------------
#  Процессор-обёртка: гарантирует, что ошибка внутри процессора
#  не сломает всё приложение.
# --------------------------------------------------------------
class SafeProcessor:
    """
    Оборачивает любой structlog-процессор. Если тот бросает исключение,
    перехватываем и пишем в stderr, но event_dict возвращаем как есть,
    чтобы не потерять лог и не сломать запрос.
    """

    def __init__(self, processor: structlog.types.Processor) -> None:
        self.processor = processor
        self._name: str = getattr(processor, "__name__", repr(processor))

    def __call__(
        self, logger: Any, method_name: str, event_dict: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            return self.wrapped(logger, method_name, event_dict)
        except Exception as exc:
            print(
                f"[LOGGER-INTERNAL-ERROR] Processor {self._name} failed: "
                f"{type(exc).__name__}: {exc}",
                file=sys.stderr,
                flush=True,
            )
            return event_dict


# ---------------------------------------------------------------------------
#  Настройка stdlib logging (файл + stdout)
# ---------------------------------------------------------------------------
def _configure_stdlib_logging() -> None:
    """
    Настраивает корневой logging на запись JSON-строк structlog:
    - StreamHandler в stdout (всегда)
    - RotatingFileHandler в файл (если LOG_DIR задан)
    """
    root = logging.getLogger()
    root.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))

    formatter = logging.Formatter("%(message)s")

    # stdout handler
    has_stdout = any(
        isinstance(handler, logging.StreamHandler)
        and getattr(handler, "stream", None) is sys.stdout
        for handler in root.handlers
    )
    if not has_stdout:
        stdout_handler = logging.StreamHandler(sys.stdout)
        stdout_handler.setFormatter(formatter)
        root.addHandler(stdout_handler)

    # file handler (RotatingFileHandler - безопасный append)
    if LOG_DIR:
        os.makedirs(LOG_DIR, exist_ok=True)
        log_path: str = os.path.join(LOG_DIR, LOG_FILE_NAME)
        has_file = any(
            isinstance(h, RotatingFileHandler) for h in root.handlers
        )
        if not has_file:
            file_handler = RotatingFileHandler(
                filename=log_path,
                maxBytes=LOG_MAX_BYTES,
                backupCount=LOG_BACKUP_COUNT,
                encoding="utf-8",
            )
            file_handler.setFormatter(formatter)
            root.addHandler(file_handler)

    # Отключаем werkzeug-спам
    logging.getLogger("werkzeug").setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
#  Инициализация structlog
# ---------------------------------------------------------------------------
_logger_configured: bool = False


def setup_logger() -> None:
    """
    Настраивает structlog + stdlib logging.
    Вызывается один раз при импорте модуля. 
    """
    global _logger_configured
    if _logger_configured:
        return
    _logger_configured = True

    _configure_stdlib_logging()

    # Уровень фильтрации для make_filtering_bound_logger
    min_level: int = getattr(logging, LOG_LEVEL.upper(), logging.INFO)

    structlog.configure(
        processors=[
            # Метка времени ISO 8601 (UTC)
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            # Уровень логирования
            structlog.processors.add_log_level,
            # Callsite: файл, функция, номер строки
            SafeProcessor(
                structlog.processors.CallsiteParameterAdder(
                    {
                        CallsiteParameter.FILENAME,
                        CallsiteParameter.FUNC_NAME,
                        CallsiteParameter.LINENO,
                    }
                )
            ),
            # Стек и tracebacks
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.format_exc_info,
            # Данные HTTP-запроса
            SafeProcessor(add_request_context),
            # Финальный рендеринг: JSON-строка (кириллица, datetime)
            structlog.processors.JSONRenderer(
                ensure_ascii=False,
                default=str,
            ),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        # make_filtering_bound_logger возвращает класс с .info(), .debug(),
        # .error(), .exception() и т.д., совместимый с BindableLogger.
        # Фильтрация по уровню происходит ещё до входа в цепочку процессоров.
        wrapper_class=structlog.make_filtering_bound_logger(min_level),
        cache_logger_on_first_use=True,
    )


def init_logger() -> structlog.stdlib.BoundLogger:
    """
    Возвращает готовый к использованию логгер.
    """
    return structlog.get_logger()


# Автоматически настраиваем при первом импорте
setup_logger()
