from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

from sqlalchemy import and_, asc, desc, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from app import db
from app.models import Tag, TestCase, TestCaseStep, TestCaseSuite, TestSuite
from constants import ASCII_CODING, ENCODING, TESTCASE_PER_PAGE_LIMIT


# -------------------------------
# Исключения, специфичные для домена
# -------------------------------
class TestCaseError(Exception):
    """Базовое исключение для ошибок, связанных с TestCase.

    Используется для того, чтобы маршруты могли перехватывать и корректно
    сопоставлять исключения с HTTP-ответами.
    """


class ValidationError(TestCaseError):
    """Ошибка валидации входных данных (эквивалент HTTP 400).

    Бросается при неверной структуре payload, отсутствующих обязательных полях
    или при логических конфликтах (например, дубликат позиции шага).
    """


class NotFoundError(TestCaseError):
    """Сущность не найдена (эквивалент HTTP 404)."""


class ConflictError(TestCaseError):
    """Ошибка конфликта (эквивалент HTTP 409).

    Используется для того, чтобы узнать о нарушении например уникальности имени тест-кейса.
    """


# -------------------------------
# Вспомогательные утилиты
# -------------------------------
def _ensure_list(value: Optional[Iterable]) -> List:
    """Гарантирует, что возвращается список (не None).

    Если value == None возвращаем пустой список. Удобно для полей payload,
    которые могут быть опущены в запросе.
    """
    return list(value) if value is not None else []


def _validate_basic_fields(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Базовая валидация и нормализация полей payload.

    Проверяем обязательное поле 'name' и нормализуем опциональные поля.
    Возвращаем нормализованный словарь для дальнейшей обработки.
    """
    name = payload.get("name")
    if not name or not isinstance(name, str) or not name.strip():
        raise ValidationError("Поле 'name' обязательно и не должно быть пустой строкой")

    normalized = {
        "name": name.strip(),
        "preconditions": payload.get("preconditions"),
        "description": payload.get("description"),
        "expected_result": payload.get("expected_result"),
        # Гарантируем списки, даже если ключи отсутствуют
        "steps": _ensure_list(payload.get("steps")),
        "tags": _ensure_list(payload.get("tags")),
        "suite_links": _ensure_list(payload.get("suite_links")),
    }

    # Простые валидации типов
    if not isinstance(normalized["steps"], list):
        raise ValidationError("Поле 'steps' должно быть списком")
    if not isinstance(normalized["tags"], list):
        raise ValidationError("Поле 'tags' должно быть списком")
    if not isinstance(normalized["suite_links"], list):
        raise ValidationError("Поле 'suite_links' должно быть списком")

    return normalized


# -------------------------------
# Tag helpers
# -------------------------------
def _get_tag_by_id(tag_id: int) -> Optional[Tag]:
    """Возвращает Tag по ID или None."""
    return Tag.query.get(tag_id)


def _get_tag_by_name(name: str) -> Optional[Tag]:
    """Возвращает Tag по имени или None."""
    return Tag.query.filter_by(name=name).first()


def _normalize_tag_input(raw: Union[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Преобразует входное представление тега в нормализованную форму.

    Принимается либо строка (имя тега), либо объект {"id": ...} / {"name": ...}.
    Если вход пустой/пустая строка — возвращается {"skip": True}.
    """
    if isinstance(raw, str):
        return {"name": raw.strip()} if raw.strip() else {"skip": True}
    if isinstance(raw, dict):
        if "id" in raw:
            return {"id": int(raw["id"])}
        if "name" in raw:
            return (
                {"name": str(raw["name"]).strip()}
                if str(raw["name"]).strip()
                else {"skip": True}
            )
    # Неправильный формат
    raise ValidationError(
        "Каждый тег должен быть строкой (именем) или объектом, содержащим 'id' или 'name'"
    )


def _get_or_create_tag(normalized: Dict[str, Any]) -> Optional[Tag]:
    """Возвращает существующий Tag или создаёт новый по имени.

    Поведение:
    - Если передан 'id' и тег найден -> возвращаем его.
    - Если передан 'id' и тег НЕ найден -> возвращаем None (и логируем),
      чтобы вызывающий код мог решить — пропустить или считать это ошибкой.
    - Если передан 'name' -> ищем по имени, создаём, если нет.
    """
    # Пытаемся взять тег по id
    if "id" in normalized:
        tag = _get_tag_by_id(normalized["id"])
        if not tag:
            # Чтобы не ломать весь payload.
            return None
        return tag

    # Создание/поиск по имени
    if "name" in normalized:
        tag_name = normalized["name"]
        tag = _get_tag_by_name(tag_name)
        if tag:
            return tag
        tag = Tag(name=tag_name)
        db.session.add(tag)
        # flush, чтобы получить id сразу
        db.session.flush()
        return tag

    raise ValidationError("Введенный тег не прошел валидацию")


# -------------------------------
# Suite helpers
# -------------------------------
def _normalize_suite_input(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Нормализация одного элемента suite_links.

    Убеждаемся, что на вход — объект и извлекаем ожидаемые поля: suite_id / suite_name / position.
    """
    if not isinstance(raw, dict):
        raise ValidationError("Каждая suite_link должна быть объектом")

    out: Dict[str, Any] = {}
    if "suite_id" in raw:
        out["suite_id"] = int(raw["suite_id"]) if raw["suite_id"] is not None else None
    if "suite_name" in raw:
        out["suite_name"] = str(raw["suite_name"]).strip()
    if "position" in raw and raw["position"] is not None:
        try:
            out["position"] = int(raw["position"])
        except Exception:
            raise ValidationError("'position' в suite_links должно быть целым числом")
    return out


def _get_suite_by_id(suite_id: int) -> Optional[TestSuite]:
    """Возвращает TestSuite по id или None."""
    return TestSuite.query.get(suite_id)


def _get_suite_by_name(name: str) -> Optional[TestSuite]:
    """Возвращает TestSuite по имени или None."""
    return TestSuite.query.filter_by(name=name).first()


def _get_or_create_suite(normalized: Dict[str, Any]) -> Optional[TestSuite]:
    """Возвращает существующий TestSuite или создаёт новый по имени.

    Поведение:
    - Если передан 'suite_id' и сьют найден -> возвращаем его.
    - Если передан 'suite_id' и сьют НЕ найден -> возвращаем None (и логируем),
      чтобы вызывающий код мог пропустить этот элемент.
    - Если передан 'suite_name' -> ищем по имени, создаём при отсутствии.
    """
    if "suite_id" in normalized and normalized["suite_id"] is not None:
        suite = _get_suite_by_id(normalized["suite_id"])
        if not suite:
            # Не бросаем NotFoundError, а возвращаем None
            return None
        return suite

    if "suite_name" in normalized and normalized["suite_name"]:
        name = normalized["suite_name"]
        suite = _get_suite_by_name(name)
        if suite:
            return suite
        now = datetime.now(timezone.utc)
        suite = TestSuite(name=name, created_at=now, updated_at=now)
        db.session.add(suite)
        db.session.flush()
        return suite

    raise ValidationError(
        "Каждый suite_link должен содержать 'suite_id' или 'suite_name'"
    )


# -------------------------------
# Steps helpers
# -------------------------------
def _normalize_step_input(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Нормализация одного шага тест-кейса.

    Убедимся, что step — объект и содержит непустой 'action'.
    Позиция может быть опущена — тогда будет назначена автоматически позже.
    """
    if not isinstance(raw, dict):
        raise ValidationError("Каждый step должен быть словарем")
    action = raw.get("action")
    if not action or not isinstance(action, str) or not action.strip():
        raise ValidationError("Каждый step должен содержать не пустой 'action'")
    out = {
        "action": action.strip(),
        "position": (
            int(raw["position"])
            if "position" in raw and raw["position"] is not None
            else None
        ),
        "expected": raw.get("expected"),
        "attachments": raw.get("attachments"),
    }
    return out


# -------------------------------
# Core operation
# -------------------------------
def create_test_case_from_payload(payload: Dict[str, Any]) -> TestCase:
    """Создаёт TestCase и связанные сущности на основе payload."""
    input_payload = _validate_basic_fields(payload)

    try:
        with db.session.begin():
            # Явно устанавливаем timestamps, чтобы не зависеть от server_default в БД
            now = datetime.now(timezone.utc)
            test_case = TestCase(
                name=input_payload["name"],
                preconditions=input_payload.get("preconditions"),
                description=input_payload.get("description"),
                expected_result=input_payload.get("expected_result"),
                created_at=now,
                updated_at=now,
            )
            db.session.add(test_case)

            # -----------------------
            # Обработка тегов
            # -----------------------
            tag_ids_seen = set()
            for raw_tag in input_payload["tags"]:
                normalized = _normalize_tag_input(raw_tag)
                if normalized.get("skip"):
                    continue
                tag = _get_or_create_tag(normalized)
                if tag is None:
                    logger = __import__(
                        "logger"
                    ).init_logger()  # аккуратно получить логгер без циклических импортов
                    logger.warning(
                        f"Тег, на который ссылается id={normalized.get('id')} не найден — пропускаем, "
                        f"тэги не обязательны"
                    )
                    continue
                if tag.id in tag_ids_seen:
                    continue
                test_case.tags.append(tag)
                tag_ids_seen.add(tag.id)

            # -----------------------
            # Обработка шагов
            # -----------------------
            auto_position = 1
            positions_seen = set()
            for raw_step in input_payload["steps"]:
                step_input = _normalize_step_input(raw_step)
                position_step_input = (
                    step_input["position"]
                    if step_input["position"] is not None
                    else auto_position
                )
                if position_step_input in positions_seen:
                    raise ValidationError(
                        f"Дубликат позиции шага: {position_step_input}"
                    )
                positions_seen.add(position_step_input)
                auto_position = max(auto_position, position_step_input + 1)
                step = TestCaseStep(
                    position=position_step_input,
                    action=step_input["action"],
                    expected=step_input.get("expected"),
                    attachments=step_input.get("attachments"),
                )
                test_case.steps.append(step)

            # -----------------------
            # Обработка связей с тест-сьютами (suite_links)
            # -----------------------
            suite_ids_seen = set()
            for raw_sl in input_payload["suite_links"]:
                normalized = _normalize_suite_input(raw_sl)
                suite = _get_or_create_suite(normalized)
                if suite is None:
                    # Если клиент указал suite_id, которого нет — пропускаем и логируем.
                    # Логер берём аккуратно, чтобы не было циклических импортов.
                    logger = __import__("logger").init_logger()
                    logger.warning(
                        f"TestSuite, на который ссылается id={normalized.get('suite_id')} не найден — "
                        f"пропускаем, для тест кейсов не обязательны сьюты"
                    )
                    continue
                if suite.id in suite_ids_seen:
                    continue
                suite_ids_seen.add(suite.id)
                link = TestCaseSuite(suite=suite, position=normalized.get("position"))
                test_case.suite_links.append(link)

            # Окончательный flush делаем один раз — когда все необходимые поля проставлены
            db.session.flush()
            db.session.refresh(test_case)

    except IntegrityError as ie:
        db.session.rollback()
        raise ConflictError(
            "Ошибка целостности бд при создании TestCase (вероятно, дублирующееся имя)"
        ) from ie

    return test_case


# -------------------------------
# Сериализатор
# -------------------------------
def serialize_test_case(tc: TestCase) -> Dict[str, Any]:
    """Преобразует TestCase в JSON-совместимый словарь.

    Сериализуем только публичные и необходимые поля — без лишних внутренних атрибутов.
    Сортируем шаги по позиции для детерминированности.
    """
    return {
        "id": tc.id,
        "name": tc.name,
        "preconditions": tc.preconditions,
        "description": tc.description,
        "expected_result": tc.expected_result,
        "created_at": tc.created_at.isoformat() if tc.created_at else None,
        "updated_at": tc.updated_at.isoformat() if tc.updated_at else None,
        "is_deleted": bool(tc.is_deleted),
        "steps": [
            {
                "id": step.id,
                "position": step.position,
                "action": step.action,
                "expected": step.expected,
                "attachments": step.attachments,
            }
            for step in sorted(tc.steps, key=lambda step: step.position)
        ],
        "tags": [{"id": tag.id, "name": tag.name} for tag in tc.tags],
        "suites": [
            {"id": link.suite.id, "name": link.suite.name, "position": link.position}
            for link in tc.suite_links
        ],
    }


# ---------- Парсинг входных параметров ----------
def parse_bool_param(raw_value: Optional[Union[str, bool]]) -> Optional[bool]:
    """
    Корректно парсит булев параметр из query string.
    Допустимые true: "1","true","yes","y" (регистр не важен).
    Допустимые false: "0","false","no","n".
    Возвращает None если вход пустой или нераспознан.
    """
    if raw_value is None:
        return None
    if isinstance(raw_value, bool):
        return raw_value
    normalized_value = str(raw_value).strip().lower()
    if normalized_value in ("1", "true", "yes", "y"):
        return True
    if normalized_value in ("0", "false", "no", "n"):
        return False
    return None


# ---------- Cursor helpers ----------
def _encode_cursor(obj: dict) -> str:
    """
    Кодируем cursor-объект (например {'created_at': 'ISO', 'id': 123})
    в URL-safe base64 строку. Возвращаем str.
    """
    # Сериализуем объект в компактную JSON-строку (без лишних пробелов)
    json_str = json.dumps(obj, separators=(",", ":"), ensure_ascii=False)
    # Кодируем JSON в байты UTF-8
    json_bytes = json_str.encode(ENCODING)
    # Кодируем байты в URL-safe base64 и возвращаем ascii-строку
    encoded_bytes = base64.urlsafe_b64encode(json_bytes)
    encoded_str = encoded_bytes.decode(ASCII_CODING)
    return encoded_str


def _decode_cursor(cursor_str: str) -> dict:
    """
    Декодируем cursor-строку, возвращаем dict.
    При ошибке бросаем ValueError.
    """
    # Декодируем base64 (получаем JSON в виде байтов)
    try:
        encoded_bytes = cursor_str.encode(ASCII_CODING)
        json_bytes = base64.urlsafe_b64decode(encoded_bytes)
        json_str = json_bytes.decode(ENCODING)
        obj = json.loads(json_str)
    except Exception as exc:
        # Пробрасываем ValueError с понятным сообщением — вызывающий код обработает это как ValidationError
        raise ValueError("Неверный формат курсора") from exc

    return obj


# ---------- Cursor-based list function ----------
def get_test_cases_cursored(
    *,
    q: Optional[str] = None,
    tags: Optional[List[str]] = None,
    suite_ids: Optional[List[int]] = None,
    suite_name: Optional[str] = None,
    limit: int = 25,
    cursor: Optional[str] = None,
    sort: str = "-created_at",
    include_deleted: bool = False,
) -> Tuple[List["TestCase"], Dict[str, Any]]:
    """
    Возвращает (items, meta) используя cursor-based pagination.

    Поддерживаемые параметры:
      - q: частичный поиск по name и description (case-insensitive)
      - tags: список имён тегов (фильтр ANY)
      - suite_ids: список id сьютов (фильтр ANY)
      - suite_name: частичный поиск по имени сьюта (case-insensitive)
      - limit: количество элементов (1..200), дефолт 25
      - cursor: курсор (base64 JSON, полученный из предыдущего ответа)
      - sort: '-created_at' или 'created_at' (допускается только created_at для курсора)
      - include_deleted: показывать удалённые записи
    Возвращает:
      - items: список объектов TestCase (SQLAlchemy)
      - meta: { next_cursor: str|None, limit: int, returned: int }
    """
    # Защита limit
    limit = int(limit or TESTCASE_PER_PAGE_LIMIT)
    limit = min(max(1, limit), 200)

    # Базовый query с eager-loading чтобы избежать N+1
    query = TestCase.query.options(
        joinedload(TestCase.tags),
        joinedload(TestCase.steps),
        joinedload(TestCase.suite_links).joinedload(TestCaseSuite.suite),
    )

    # is_deleted фильтр
    if not include_deleted:
        query = query.filter(TestCase.is_deleted.is_(False))
    else:
        query = query.filter(TestCase.is_deleted.is_(True))

    # Поиск q
    if q:
        pattern = f"%{q}%"
        query = query.filter(
            or_(TestCase.name.ilike(pattern), TestCase.description.ilike(pattern))
        )

    # Фильтрация по тегам (ANY)
    if tags:
        query = query.join(TestCase.tags).filter(Tag.name.in_(tags))

    # Фильтрация по suite_ids (ANY)
    if suite_ids:
        query = query.join(TestCase.suite_links).filter(
            TestCaseSuite.suite_id.in_(suite_ids)
        )

    # Фильтрация по suite_name (partial)
    if suite_name:
        pattern_suite = f"%{suite_name}%"
        query = (
            query.join(TestCase.suite_links)
            .join(TestCaseSuite.suite)
            .filter(TestSuite.name.ilike(pattern_suite))
        )

    # Сортировка: поддерживаем только created_at (вторичный ключ - id)
    sort_key = str(sort or "-created_at").strip()
    descending = sort_key.startswith("-")
    # если клиент передал не поддерживаемое поле — fallback на '-created_at'
    if sort_key.lstrip("-") != "created_at":
        descending = True

    primary_order = (
        desc(TestCase.created_at) if descending else asc(TestCase.created_at)
    )
    secondary_order = desc(TestCase.id) if descending else asc(TestCase.id)
    query = query.order_by(primary_order, secondary_order)

    # Применяем курсор (если он есть)
    if cursor:
        try:
            cur_obj = _decode_cursor(cursor)
            cursor_created_at = datetime.fromisoformat(cur_obj["created_at"])
            cursor_id = int(cur_obj["id"])
        except Exception as exc:
            # нормализуем ошибку в доменную ValidationError на уровне вызывающего кода
            raise ValueError("Invalid cursor") from exc

        if descending:
            # (created_at < cursor_created_at) OR (created_at == cursor_created_at AND id < cursor_id)
            query = query.filter(
                or_(
                    TestCase.created_at < cursor_created_at,
                    and_(
                        TestCase.created_at == cursor_created_at,
                        TestCase.id < cursor_id,
                    ),
                )
            )
        else:
            # (created_at > cursor_created_at) OR (created_at == cursor_created_at AND id > cursor_id)
            query = query.filter(
                or_(
                    TestCase.created_at > cursor_created_at,
                    and_(
                        TestCase.created_at == cursor_created_at,
                        TestCase.id > cursor_id,
                    ),
                )
            )

    # Получаем limit+1 записей, чтобы понять, есть ли next page
    rows = query.limit(limit + 1).all()
    has_more = len(rows) > limit
    items = rows[:limit]

    # Формируем next_cursor по последнему элементу (если есть next)
    next_cursor = None
    if has_more and items:
        last = items[-1]
        cur_obj = {"created_at": last.created_at.isoformat(), "id": last.id}
        next_cursor = _encode_cursor(cur_obj)

    meta = {"next_cursor": next_cursor, "limit": limit, "returned": len(items)}
    return items, meta
