from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Union

from sqlalchemy.exc import IntegrityError

from app import db
from app.models import Tag, TestCase, TestCaseStep, TestCaseSuite, TestSuite


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
