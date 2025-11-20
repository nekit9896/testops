from __future__ import annotations

import base64
import json
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

from flask import current_app
from sqlalchemy import and_, asc, desc, func, or_
from sqlalchemy.exc import IntegrityError, InvalidRequestError
from sqlalchemy.orm import joinedload

import app.models as models
from app import db
from app.clients import MinioClient
from constants import ASCII_CODING, ENCODING, TESTCASE_PER_PAGE_LIMIT

minio_client = MinioClient()


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
def _get_tag_by_id(tag_id: int) -> Optional[models.Tag]:
    """Возвращает Tag по ID или None."""
    return models.Tag.query.get(tag_id)


def _get_tag_by_name(name: str) -> Optional[models.Tag]:
    """Возвращает Tag по имени или None."""
    return models.Tag.query.filter_by(name=name).first()


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


def _get_or_create_tag(normalized: Dict[str, Any]) -> Optional[models.Tag]:
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

        tag = models.Tag(name=tag_name)
        db.session.add(tag)
        try:
            db.session.flush()  # пытаемся получить id сразу
        except IntegrityError:
            # Вероятно, другая транзакция создала такой тег между SELECT и INSERT.
            # Откатываем локальный flush (не всю внешнюю транзакцию) и пробуем SELECT снова.
            db.session.rollback()
            tag = _get_tag_by_name(tag_name)
            if tag:
                return tag
            # Если всё ещё нет — пробрасываем, пусть вызывающий код решает.
            raise
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


def _get_suite_by_id(suite_id: int) -> Optional[models.TestSuite]:
    """Возвращает TestSuite по id или None."""
    return models.TestSuite.query.get(suite_id)


def _get_suite_by_name(name: str) -> Optional[models.TestSuite]:
    """Возвращает TestSuite по имени или None."""
    return models.TestSuite.query.filter_by(name=name).first()


def _get_or_create_suite(normalized: Dict[str, Any]) -> Optional[models.TestSuite]:
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
        suite = models.TestSuite(name=name, created_at=now, updated_at=now)
        db.session.add(suite)
        try:
            db.session.flush()
        except IntegrityError:
            db.session.rollback()
            suite = _get_suite_by_name(name)
            if suite:
                return suite
            raise
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
def create_test_case_from_payload(payload: Dict[str, Any]) -> models.TestCase:
    """Создаёт TestCase и связанные сущности на основе payload."""
    input_payload = _validate_basic_fields(payload)

    try:
        with _transaction_context():
            # Явно устанавливаем timestamps, чтобы не зависеть от server_default в БД
            now = datetime.now(timezone.utc)
            test_case = models.TestCase(
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
                step = models.TestCaseStep(
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
                link = models.TestCaseSuite(
                    suite=suite, position=normalized.get("position")
                )
                test_case.suite_links.append(link)

            # Если мы добавили этот тест-кейс в уже помеченные как deleted sutes —
            # сделаем их видимыми (is_deleted = False)
            if suite_ids_seen:
                for suite_id in suite_ids_seen:
                    suite_obj = models.TestSuite.query.get(suite_id)
                    if suite_obj and suite_obj.is_deleted:
                        suite_obj.is_deleted = False
                        db.session.add(suite_obj)

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
def serialize_test_case(tc: models.TestCase) -> Dict[str, Any]:
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
) -> Tuple[List["models.TestCase"], Dict[str, Any]]:
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
    query = models.TestCase.query.options(
        joinedload(models.TestCase.tags),
        joinedload(models.TestCase.steps),
        joinedload(models.TestCase.suite_links).joinedload(models.TestCaseSuite.suite),
    )

    # is_deleted фильтр
    if not include_deleted:
        query = query.filter(models.TestCase.is_deleted.is_(False))
    else:
        query = query.filter(models.TestCase.is_deleted.is_(True))

    # Поиск q
    if q:
        pattern = f"%{q}%"
        query = query.filter(
            or_(
                models.TestCase.name.ilike(pattern),
                models.TestCase.description.ilike(pattern),
            )
        )

    # Фильтрация по тегам (ANY)
    if tags:
        query = query.join(models.TestCase.tags).filter(models.Tag.name.in_(tags))

    # Фильтрация по suite_ids (ANY)
    if suite_ids:
        query = query.join(models.TestCase.suite_links).filter(
            models.TestCaseSuite.suite_id.in_(suite_ids)
        )

    # Фильтрация по suite_name (partial)
    if suite_name:
        pattern_suite = f"%{suite_name}%"
        query = (
            query.join(models.TestCase.suite_links)
            .join(models.TestCaseSuite.suite)
            .filter(models.TestSuite.name.ilike(pattern_suite))
        )

    # Сортировка: поддерживаем только created_at (вторичный ключ - id)
    sort_key = str(sort or "-created_at").strip()
    descending = sort_key.startswith("-")
    # если клиент передал не поддерживаемое поле — fallback на '-created_at'
    if sort_key.lstrip("-") != "created_at":
        descending = True

    primary_order = (
        desc(models.TestCase.created_at)
        if descending
        else asc(models.TestCase.created_at)
    )
    secondary_order = (
        desc(models.TestCase.id) if descending else asc(models.TestCase.id)
    )
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
                    models.TestCase.created_at < cursor_created_at,
                    and_(
                        models.TestCase.created_at == cursor_created_at,
                        models.TestCase.id < cursor_id,
                    ),
                )
            )
        else:
            # (created_at > cursor_created_at) OR (created_at == cursor_created_at AND id > cursor_id)
            query = query.filter(
                or_(
                    models.TestCase.created_at > cursor_created_at,
                    and_(
                        models.TestCase.created_at == cursor_created_at,
                        models.TestCase.id > cursor_id,
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


def get_test_case_by_id(
    test_case_id: int, *, include_deleted: bool = False
) -> models.TestCase:
    """
    Получает TestCase по его id с eager-loading связанных сущностей.

    Поведение:
      - Если TestCase с переданным id не найден -> бросает NotFoundError.
      - Если TestCase найден, но помечен is_deleted и include_deleted == False -> тоже бросает NotFoundError.
      - Возвращает объект TestCase  при успешном поиске.
    Параметры:
      - test_case_id: int — идентификатор искомого TestCase.
      - include_deleted: bool — если True, разрешаем возвращать помеченные как удалённые записи.

    Использует joinedload для подгрузки связей: steps, tags, suite_links->suite.
    """
    # Валидация аргумента
    if not isinstance(test_case_id, int) or test_case_id <= 0:
        raise ValidationError("test_case_id должен быть положительным целым числом")

    # Используем joinedload, чтобы сразу подгрузить все нужные связи и избежать N+1
    query = models.TestCase.query.options(
        joinedload(models.TestCase.steps),
        joinedload(models.TestCase.tags),
        joinedload(models.TestCase.suite_links).joinedload(models.TestCaseSuite.suite),
    )

    # Получаем объект
    test_case = query.get(test_case_id)

    if not test_case:
        raise NotFoundError(f"TestCase с id={test_case_id} не найден")

    # Если найден, но помечен как удалённый — по умолчанию скрываем
    if test_case.is_deleted and not include_deleted:
        raise NotFoundError(f"TestCase с id={test_case_id} удален")

    return test_case


# --------- Транзакционный helper ---------
@contextmanager
def _transaction_context():
    """
    Контекст-менеджер транзакции.
    - Если сессия уже в транзакции -> используем begin_nested() (SAVEPOINT).
    - Иначе -> обычный db.session.begin().
    Важно: НЕ делать никаких вызовов, которые проверяют/открывают соединение
    до входа в этот контекст (например db.session.get_bind(), db.session.connection()
    или любые SELECT), т.к. они вызовут implicit BEGIN.
    """
    logger = __import__("logger").init_logger()

    # Определяем, кажется ли сессия уже в транзакции (без побочных эффектов).
    try:
        session_in_transaction = bool(
            getattr(db.session, "in_transaction", lambda: False)()
        )
    except Exception:
        session_in_transaction = getattr(db.session, "transaction", None) is not None

    logger.debug(
        f"_transaction_context: session_in_transaction={session_in_transaction}"
    )

    # аккуратно вычисляем, кажется ли сессия в транзакции
    try:
        in_transaction_flag = bool(
            getattr(db.session, "in_transaction", lambda: False)()
        )
    except Exception:
        in_transaction_flag = getattr(db.session, "transaction", None) is not None

    # Открываем нормальную транзакцию или nested (savepoint) в зависимости от состояния.
    try:
        transaction_context_manager = db.session.begin()
        used = "begin"
    except InvalidRequestError:
        transaction_context_manager = db.session.begin_nested()
        used = "begin_nested"

    logger.debug(
        f"_transaction_context: entering ({used}), in_transaction={in_transaction_flag}"
    )
    try:
        with transaction_context_manager:
            yield
    finally:
        logger.debug(f"_transaction_context: exit ({used})")


# --------- Update TestCase logic ---------
def update_test_case_from_payload(
    test_case_id: int, payload: Dict[str, Any]
) -> models.TestCase:
    """
    Обновляет TestCase и связанные сущности на основании полученного payload.

    Семантика: полный апдейт (PUT) — клиент передаёт полное представление
    тест-кейса (то же, что для создания). Функция атомарна: все изменения
    выполняются внутри транзакции; при ошибке происходит откат.

    Поведение:
      - Если TestCase с данным id не найден или помечен is_deleted -> NotFoundError.
      - Валидирует payload (использует _validate_basic_fields) — требует 'name'.
      - Обновляет поля name, preconditions, description, expected_result.
      - Полностью заменяет steps (удаляет старые, создаёт новые).
      - Заменяет теги: ищет/создаёт теги по имени, если указан id и тега нет — пропускает и логирует.
      - Заменяет suite_links: по suite_id ищет, по suite_name — создаёт при необходимости;
        если указан suite_id, которого нет — пропускает и логирует.
      - Ловит IntegrityError и превращает в ConflictError (409).
      - Возвращает обновлённый объект TestCase (подключённый к сессии).
    """
    # Небольшая валидация аргумента
    if not isinstance(test_case_id, int) or test_case_id <= 0:
        raise ValidationError("test_case_id должен быть положительным целым числом")

    normalized = _validate_basic_fields(payload)
    logger = __import__("logger").init_logger()

    try:
        # Контекст-менеджер гарантирует commit/rollback. Входим в транзакцию прежде, чем делать SELECT/UPDATE/INSERT
        with _transaction_context():
            # Получаем текущий объект внутри транзакции (важное изменение)
            tc = models.TestCase.query.options(
                joinedload(models.TestCase.steps),
                joinedload(models.TestCase.tags),
                joinedload(models.TestCase.suite_links).joinedload(
                    models.TestCaseSuite.suite
                ),
            ).get(test_case_id)

            if not tc or tc.is_deleted:
                raise NotFoundError(f"TestCase with id={test_case_id} not found")

            # сохраняем старые suite_ids до удаления связей
            old_suite_ids = {link.suite_id for link in getattr(tc, "suite_links", [])}

            # -----------------------
            # Обновляем теги (replace)
            # -----------------------
            new_tags: List[models.Tag] = []
            tag_ids_seen = set()
            for raw_tag in normalized["tags"]:
                tag_norm = _normalize_tag_input(raw_tag)
                if tag_norm.get("skip"):
                    continue
                tag_obj = _get_or_create_tag(tag_norm)
                if tag_obj is None:
                    logger.warning(
                        f"При обновлении TestCase id={test_case_id}: "
                        f"указанный тег id={tag_norm.get('id')} не найден — пропускаем"
                    )
                    continue
                if tag_obj.id in tag_ids_seen:
                    continue
                tag_ids_seen.add(tag_obj.id)
                new_tags.append(tag_obj)

            # Назначаем новую коллекцию тегов (ORM SQLAlchemy обновит association table)
            tc.tags[:] = new_tags

            # -----------------------
            # Обновляем шаги (replace все шаги)
            # -----------------------
            # 1) Помечаем старые шаги для удаления через коллекцию (delete-orphan настроен)
            tc.steps[:] = []

            # 2) Явно делаем flush, чтобы DELETE были отправлены в БД до INSERT новых строк.
            # Это оказалось критично, иначе в некоторых случаях автосброс (autoflush) может привести
            # к попытке вставки новых шагов до удаления старых -> UniqueViolation.
            db.session.flush()

            # 3) Создаём и добавляем новые шаги в коллекцию
            auto_position = 1
            positions_seen = set()
            for raw_step in normalized["steps"]:
                norm_step = _normalize_step_input(raw_step)
                position = (
                    norm_step["position"]
                    if norm_step["position"] is not None
                    else auto_position
                )
                if position in positions_seen:
                    raise ValidationError(f"Duplicate step position: {position}")
                positions_seen.add(position)
                auto_position = max(auto_position, position + 1)
                step = models.TestCaseStep(
                    position=position,
                    action=norm_step["action"],
                    expected=norm_step.get("expected"),
                    attachments=norm_step.get("attachments"),
                )
                tc.steps.append(step)

            # -----------------------
            # Обновляем связи с тест-сьютами (replace)
            # -----------------------
            # Удаляем старые связи через коллекцию
            tc.suite_links[:] = []
            # Убеждаемся, что удаление ссылок выполняется перед новыми вставками
            db.session.flush()

            suite_ids_seen = set()
            for raw_suite_link in normalized["suite_links"]:
                norm_suite_link = _normalize_suite_input(raw_suite_link)
                suite_obj = _get_or_create_suite(norm_suite_link)
                if suite_obj is None:
                    logger.warning(
                        f"При обновлении TestCase id={test_case_id}: "
                        f"указанный TestSuite id={norm_suite_link.get('suite_id')} не найден — пропускаем"
                    )
                    continue
                if suite_obj.id in suite_ids_seen:
                    continue
                suite_ids_seen.add(suite_obj.id)
                link = models.TestCaseSuite(
                    suite=suite_obj, position=norm_suite_link.get("position")
                )
                tc.suite_links.append(link)
            # -----------------------
            # Обрабатываем изменения флагов is_deleted у affected suites
            # -----------------------
            new_suite_ids = suite_ids_seen
            added = new_suite_ids - old_suite_ids
            removed = old_suite_ids - new_suite_ids

            # Для добавленных сьютов: гарантируем, что они видимы
            for suite_id in added:
                suite_obj = models.TestSuite.query.get(suite_id)
                if suite_obj and suite_obj.is_deleted:
                    suite_obj.is_deleted = False
                    db.session.add(suite_obj)

            # Для удалённых сьютов: если они стали пустыми (нет активных кейсов) — пометить is_deleted=True
            for suite_id in removed:
                active_count = (
                    db.session.query(func.count(models.TestCaseSuite.test_case_id))
                    .join(
                        models.TestCase,
                        models.TestCaseSuite.test_case_id == models.TestCase.id,
                    )
                    .filter(
                        models.TestCaseSuite.suite_id == suite_id,
                        models.TestCase.is_deleted.is_(False),
                    )
                    .scalar()
                )
                if not active_count:
                    suite_obj = models.TestSuite.query.get(suite_id)
                    if suite_obj and not suite_obj.is_deleted:
                        suite_obj.is_deleted = True
                        db.session.add(suite_obj)

            now = datetime.now(timezone.utc)

            # Обновляем простые поля
            tc.name = normalized["name"]
            tc.preconditions = normalized.get("preconditions")
            tc.description = normalized.get("description")
            tc.expected_result = normalized.get("expected_result")
            tc.updated_at = now

            # Финальный flush и refresh
            db.session.flush()
            db.session.refresh(tc)

            return tc

    except IntegrityError as ie:
        # Откат транзакции и информативное исключение для роутера
        db.session.rollback()
        raise ConflictError(
            "Ошибка целостности бд при обновлении TestCase (возможно, имя уже занято)"
        ) from ie


def soft_delete_test_case(test_case_id: int) -> models.TestCase:
    """
    Soft-delete TestCase: пометить запись как удалённую, не удаляя дочерние записи
    (steps, suite_links, tags) — чтобы при возможном восстановлении они автоматически
    вернулись и на фронте.

    Поведение:
      - Если тест-кейс не найден -> NotFoundError.
      - Идемпотентно: если уже is_deleted -> возвращаем объект.
      - В транзакции: помечаем tc.is_deleted=True, tc.deleted_at и tc.updated_at.
      - Flush + refresh и возвращаем tc.
    """
    if not isinstance(test_case_id, int) or test_case_id <= 0:
        raise ValidationError("test_case_id должен быть положительным целым числом")

    logger = __import__("logger").init_logger()

    try:
        with _transaction_context():
            # Загружаем объект внутри транзакции
            tc = models.TestCase.query.options(
                joinedload(models.TestCase.steps),
                joinedload(models.TestCase.tags),
                joinedload(models.TestCase.suite_links).joinedload(
                    models.TestCaseSuite.suite
                ),
            ).get(test_case_id)

            if not tc:
                raise NotFoundError(f"TestCase with id={test_case_id} not found")

            if tc.is_deleted:
                # Идемпотентно — уже удалён
                return tc

            now = datetime.now(timezone.utc)

            # Просто помечаем тест-кейс как удалённый
            tc.is_deleted = True
            tc.deleted_at = now
            tc.updated_at = now

            attachments = models.Attachment.query.filter_by(test_case_id=tc.id).all()
            for attachment in attachments:
                try:
                    minio_client.remove_object(
                        attachment.bucket, attachment.object_name
                    )
                except Exception:
                    current_app.logger.exception(
                        "Не удалось удалить вложение из minio для test_case %s attachment %s",
                        tc.id,
                        attachment.id,
                    )
                    raise

            # Удаляем метаданные
            models.Attachment.query.filter_by(test_case_id=tc.id).delete(
                synchronize_session=False
            )

            db.session.flush()

            # получаем уникальные id сьютов, в которых был этот кейс
            suite_ids = {link.suite_id for link in getattr(tc, "suite_links", [])}

            for suite_id in suite_ids:
                # count активных (is_deleted == False) кейсов в этом suite
                active_count = (
                    db.session.query(func.count(models.TestCaseSuite.test_case_id))
                    .join(
                        models.TestCase,
                        models.TestCaseSuite.test_case_id == models.TestCase.id,
                    )
                    .filter(
                        models.TestCaseSuite.suite_id == suite_id,
                        models.TestCase.is_deleted.is_(False),
                    )
                    .scalar()
                )
                if not active_count or int(active_count) == 0:
                    suite = models.TestSuite.query.get(suite_id)
                    if suite and not suite.is_deleted:
                        suite.is_deleted = True
                        db.session.add(suite)

            # гарантируем, что объекты обновлены в сессии
            db.session.flush()
            db.session.refresh(tc)

    except IntegrityError as ie:
        db.session.rollback()
        logger.exception("IntegrityError при soft-delete TestCase", exc_info=ie)
        raise ConflictError("Ошибка целостности бд при удалении TestCase") from ie

    return tc
