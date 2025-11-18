# app/helpers/allure_utils.py
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def _parse_properties_text(properties_text: str) -> Dict[str, str]:
    """
    Парсит текст формата key=value в словарь.
    Игнорирует пустые строки и комментарии, начинающиеся с '#'.
    """
    result: Dict[str, str] = {}
    for raw_line in properties_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, value = line.split("=", 1)
            result[key.strip()] = value.strip()
    return result


def _parse_json_text(json_text: str) -> Optional[Dict[str, Any]]:
    """
    Пытается распарсить текст как JSON. Возвращает dict при успехе, иначе None.
    """
    try:
        parsed = json.loads(json_text)
        if isinstance(parsed, dict):
            return parsed
        # если JSON — не объект, считаем неподходящим форматом
        return None
    except Exception:
        return None


def _read_text_from_file(file_path: Path) -> str:
    """
    Читает файл как текст utf-8 с игнорированием ошибок декодирования.
    """
    return file_path.read_text(encoding="utf-8", errors="ignore")


def _extract_properties_from_content(file_content: str) -> Dict[str, str]:
    """
    Универсальный парсер содержимого environment-файла:
     - если контент похож на JSON (начинается с '{' или может быть валидным JSON), пытается JSON-парсинг;
     - при успешном JSON-парсинге и если это dict — превращает его в словарь строковых значений;
     - если JSON-парсинг не сработал — использует properties-парсер key=value.
    Возвращает словарь string->string (пустой словарь при отсутствии парсилуемых данных).
    """
    content_stripped = file_content.lstrip()
    # попытаемся сначала JSON, когда контент похоже на JSON или вообще валидный JSON
    if content_stripped.startswith("{"):
        json_obj = _parse_json_text(file_content)
        if json_obj:
            # конвертируем значения в строки для единообразия
            return {str(k): str(v) for k, v in json_obj.items()}
        # если не JSON — fallthrough к properties
    else:
        # даже если не начинается с {, всё равно пробуем parse_json на случай, если есть пробелы/ BOM
        json_obj = _parse_json_text(file_content)
        if json_obj:
            return {str(k): str(v) for k, v in json_obj.items()}

    # fallback: классический properties парсер
    return _parse_properties_text(file_content)


def extract_stand_from_environment_file(file_path: str | Path) -> Optional[str]:
    """
    Читает заданный файл (environment.properties) и извлекает значение 'stand'.
    Поддерживает:
      - JSON-представление: { "stand": "test4", ... }
      - properties-представление: stand=test4
    Также смотрит на fallback-ключи: 'stand_name', 'environment', 'env'.
    Возвращает строку с именем стенда или None, если ключ не найден / чтение упало.
    """
    path = Path(file_path)
    if not path.exists() or not path.is_file():
        logger.debug("Environment file not found or is not a file: %s", path)
        return None

    try:
        raw_text = _read_text_from_file(path)
        properties = _extract_properties_from_content(raw_text)
        # основной ключ
        stand_value = properties.get("stand")
        if stand_value:
            return stand_value.strip()
        # возможные альтернативные ключи
        for fallback_key in ("stand_name", "environment", "env"):
            fallback_value = properties.get(fallback_key)
            if fallback_value:
                return fallback_value.strip()
        return None
    except Exception as error:
        logger.exception(
            "Failed to extract 'stand' from environment file %s: %s", path, error
        )
        return None
