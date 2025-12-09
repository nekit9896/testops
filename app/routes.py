import re
from typing import List, Optional

import flask as flask
from sqlalchemy.exc import DatabaseError
from werkzeug.routing import BuildError

import constants as const
import helpers.testcase_attachment_helpers as attach_help
import helpers.testcase_helpers as testcase_help
from app import db
from app.clients import MinioClient
from app.models import Attachment, TestCase, TestResult
from helpers import testrun_helpers
from logger import init_logger

bp = flask.Blueprint("routes", __name__)
minio_client = MinioClient()
logger = init_logger()


def _parse_test_case_payload_from_form() -> Optional[dict]:
    """
    Fallback-парсер для form-data (urlencoded/multipart) при отсутствии JSON.
    Поддерживает простые поля, теги (через запятую), suite_links (через запятую),
    шаги вида steps[0][action]/[expected]/[position].
    """
    form = flask.request.form or {}
    payload = {}

    for f in ("name", "preconditions", "description", "expected_result"):
        if f in form:
            payload[f] = form.get(f)

    tags_raw = form.get("tags")
    if tags_raw is not None:
        payload["tags"] = [t.strip() for t in tags_raw.split(",") if t.strip()]

    suites_raw = form.get("suite_links") or form.get("suites")
    if suites_raw:
        suites = [s.strip() for s in suites_raw.split(",") if s.strip()]
        payload["suite_links"] = [{"suite_name": s} for s in suites]

    steps_regex = re.compile(r"^steps\[(\d+)\]\[(action|expected|position)\]$")
    steps_map = {}
    for key, val in form.items():
        m = steps_regex.match(key)
        if not m:
            continue
        idx = int(m.group(1))
        field = m.group(2)
        steps_map.setdefault(idx, {})
        if field == "position":
            try:
                steps_map[idx][field] = int(val)
            except Exception:
                steps_map[idx][field] = None
        else:
            steps_map[idx][field] = val

    if steps_map:
        steps_list = []
        for i in sorted(steps_map.keys()):
            s = steps_map[i]
            steps_list.append(
                {
                    "position": s.get("position"),
                    "action": s.get("action", "") or "",
                    "expected": s.get("expected", "") or "",
                }
            )
        payload["steps"] = steps_list

    return payload if payload else None


def _get_test_case_payload() -> Optional[dict]:
    """Унифицированный источник payload: JSON или form."""
    payload = flask.request.get_json(silent=True)
    if payload:
        return payload
    return _parse_test_case_payload_from_form()


@bp.route("/", methods=["GET"])
@bp.route("/index", methods=["GET"])
@bp.route("/index/", methods=["GET"])
def home():
    """
    Домашняя страница
    """
    response = flask.render_template(const.TEMPLATE_INDEX)
    logger.info("Обработан запрос на главную страницу")
    return response


@bp.route("/health", methods=["GET"])
def health_check():
    response = flask.jsonify({"status": "ok"})
    logger.info("Обработан запрос на проверку доступности")
    return response


@bp.route("/upload", methods=["POST"])
def upload_results():
    """
    API-метод для загрузки файлов и создания тестового запуска
    """
    files = testrun_helpers.get_request_files()
    testrun_helpers.check_files_size(files)

    new_result = testrun_helpers.create_temp_test_result()
    test_run_info = testrun_helpers.extract_test_run_info(files)

    try:
        testrun_helpers.update_test_result(new_result, test_run_info)
        logger.info(f"Обновлены данные тестрана с ID: {new_result.id}")
    except DatabaseError as error_msg:
        db.session.rollback()
        logger.exception("Ошибка при сохранении статуса тестрана в базу данных")
        flask.abort(500, description=str(error_msg))

    success_files, error_files = testrun_helpers.upload_all_files(
        new_result.run_name, files
    )

    if success_files:
        logger.info(f"Успешно загруженные файлы в MinIO: {', '.join(success_files)}")
    if error_files:
        logger.warning(f"Ошибка обработки следующих файлов: {', '.join(error_files)}")
        flask.abort(500, description="Некоторые файлы не были успешно обработаны")

    testrun = testrun_helpers.get_existing_run_or_abort(new_result.id)
    testrun_helpers.get_or_generate_report(testrun.run_name)

    response = flask.jsonify(
        {"run_id": new_result.id, "message": "Файлы успешно загружены"}
    )
    response_code = 201
    logger.info("Файлы успешно загружены", status_code=response_code)
    return response, response_code


@bp.route("/reports", methods=["GET"])
def get_reports():
    """
    Возвращает страницу со списком отчетов
    """
    return flask.render_template(
        const.TEMPLATE_REPORTS, page_limit=const.REPORTS_PAGE_LIMIT
    )


@bp.route("/reports/data", methods=["GET"])
def get_reports_data():
    """
    Возвращает данные отчетов с курсорной пагинацией (JSON).
    """
    cursor = flask.request.args.get("cursor", type=int)
    direction = flask.request.args.get("direction", default="next", type=str).lower()
    limit = flask.request.args.get("limit", default=const.REPORTS_PAGE_LIMIT, type=int)
    limit = max(1, min(limit, 100))

    statuses = testrun_helpers.extract_filter_values("status")
    stands = testrun_helpers.extract_filter_values("stand")

    try:
        data = testrun_helpers.fetch_reports(
            cursor=cursor,
            limit=limit,
            direction=direction,
            statuses=statuses,
            stands=stands,
        )
    except ValueError as exc:
        flask.abort(400, description=str(exc))

    testrun_helpers.log_reports(bool(data["items"]))
    return flask.jsonify(data)


@bp.route("/reports/<int:result_id>", methods=["GET"])
def view_report(result_id: int):
    """
    Представление allure-report для определенного тестрана
    Данный метод выполняет следующие операции:
    1. Извлекает объект TestResult из базы данных с использованием переданного result_id.
    2. Проверяет, существует ли запись и не помечена ли она как удаленная.
       - если запись отсутствует или отмечена как удаленная, вызывается вспомогательная функция log_and_abort,
       которая регистрирует ошибку и завершает запрос.
    3. Извлекает имя тестрана (run_name) из объекта testrun.
    4. Обеспечивает наличие бакета в MinIO для хранения отчетов allure-reports.
    5. Использует функцию get_or_generate_report, чтобы либо получить существующий allure-report,
    либо сгенерировать и загрузить новый отчет, если он отсутствует.
    6. Читает содержимое HTML-файла отчета и декодирует его в строку (REST API).
    7. Возвращает содержание allure-report в виде ответа с MIME-типом text/html.
    """
    # Получение TestResult из базы данных
    testrun = TestResult.query.get(result_id)

    # Проверка на существование и статус TestResult
    if not testrun or testrun.is_deleted:
        testrun_helpers.log_and_abort(result_id, testrun)

    run_name = testrun.run_name

    # Проверка существования бакета
    minio_client.ensure_bucket_exists(const.ALLURE_REPORTS_BUCKET_NAME)

    # Получение или генерация allure-report
    html_file = testrun_helpers.get_or_generate_report(run_name)

    # Возвращает HTML как ответ
    html_content = html_file.read().decode(const.ENCODING)
    return flask.Response(html_content, mimetype="text/html")


@bp.route("/delete_test_run/<int:run_id>", methods=["DELETE"])
def delete_test_run(run_id):
    """
    Маркирует тестран как удаленный по run_id.
    ORM (Object-Relational Mapping), в нашем случае SQLAlchemy, позволяет обращаться к базе данных так,
    будто это обычный Python-объект.
    Метод получает объект TestResult по его первичному ключу (run_id),
    и если он существует, то отмечает его как удаленный (is_deleted = True)
    и сохраняет изменения в базе данных.
    """
    test_result = TestResult.query.get(run_id)

    if test_result:
        test_result.is_deleted = True
        db.session.commit()
        response = flask.jsonify({"message": "TestRun помечен как удаленный"})
        logger.info("Успешное удаление TestRun", run_id=run_id)
        return response
    else:
        error_msg = "TestRun не найден"
        logger.error(error_msg, run_id=run_id)
        flask.abort(404, description=error_msg)


@bp.route("/test_cases", methods=["POST"])
def create_test_case():
    """
    Создаёт TestCase вместе с опциональными: steps, tags, suite_links.

    Ожидаемый JSON-body:
    {
      "name": "...",
      "preconditions": "...",
      "description": "...",
      "expected_result": "...",
      "steps": [
          {"position": 1, "action": "...", "expected": "..."},
          {"action": "..."}  # position назначается автоматически
      ],
      "tags": ["smoke", {"id": 5}, {"name": "regression"}],
      "suite_links": [
          {"suite_id": 3, "position": 1},
          {"suite_name": "...", "position": 2}
      ]
    }

    Роль этой функции — обёртка HTTP <-> domain:
    - читает JSON,
    - вызывает create_test_case_from_payload (всё в transaction),
    - мапит доменные исключения на HTTP-коды,
    - возвращает 201 с Location и телом созданного ресурса.
    """
    payload = _get_test_case_payload()
    if not payload:
        logger.error("create_test_case: пустой или некорректный JSON")
        flask.abort(400, description="Invalid or missing JSON body")

    try:
        # Всю логику создания в helper — там транзакция и валидация
        tc = testcase_help.create_test_case_from_payload(payload)

    except testcase_help.ValidationError as ve:
        # Ошибки валидации входных данных -> 400 Bad Request
        logger.warning(
            "Ошибки валидации входных данных при создании TestCase", exc_info=ve
        )
        flask.abort(400, description=str(ve))

    except testcase_help.NotFoundError as ne:
        # Ссылка на несуществующий Tag/Suite -> 404 Not Found
        logger.warning(
            "Ссылка на несуществующий Tag/Suite при создании TestCase", exc_info=ne
        )
        flask.abort(404, description=str(ne))

    except testcase_help.ConflictError as ce:
        logger.warning("Конфликт при создании TestCase", exc_info=ce)
        # Если клиент ожидает HTML — попробуем flash+redirect, но защитимся от отсутствия session/secret_key
        if flask.request.accept_mimetypes.accept_html:
            try:
                flask.flash("Название тест-кейса должно быть уникальным", "error")
                return flask.redirect(flask.url_for("routes.test_cases_page"))
            except RuntimeError:
                logger.warning(
                    "Сессия недоступна flashing сообщения. Возвращаем 409.",
                    exc_info=True,
                )
                # fallback — отдаём обычный 409, обработчик ошибок вернёт страницу/JSON
                flask.abort(409, description=str(ce))

        # Для API/JSON клиентов — обычный 409
        flask.abort(409, description=str(ce))

    except DatabaseError as dbe:
        # Ошибки БД — откатываем сессию и возвращаем 500
        db.session.rollback()
        logger.exception("Ошибка БД при создании TestCase", exc_info=dbe)
        flask.abort(500, description="Ошибка базы данных")

    except Exception as e:
        # Непредвиденные ошибки — откат и 500
        db.session.rollback()
        logger.exception("Непредвиденная ошибка при создании TestCase", exc_info=e)
        flask.abort(500, description="Неожиданная ошибка")

    # Успех — сериализуем и возвращаем 201 Created с локой
    body = testcase_help.serialize_test_case(tc)
    try:
        # Пытаемся сформировать URL через именованный роут get_test_case
        location = flask.url_for("routes.get_test_case", id=tc.id)
    except BuildError:
        # Если детального роутa ещё нет — используем fallback путь
        location = f"/test_cases/{tc.id}"

    # Если клиент принимает html — редирект на страницу тест кейсов с выбранным кейсом
    if flask.request.accept_mimetypes.accept_html:
        return flask.redirect(
            flask.url_for("routes.test_cases_page", selected_id=tc.id)
        )
    return flask.jsonify(body), 201, {"Location": location}


@bp.route("/test_cases", methods=["GET"])
def list_test_cases():
    """
    Список тест-кейсов с cursor-based pagination.

    Параметры запроса:
      - q: поиск по name/description
      - tag: можно указать несколько (?tag=smoke&tag=regression)
      - suite_id: можно указать несколько (?suite_id=1&suite_id=2)
      - suite_name: partial search по имени сьюта
      - limit: int (1..200)
      - cursor: cursor string из предыдущего ответа
      - sort: (опционально) только 'created_at' или '-created_at' (по умолчанию '-created_at')
      - include_deleted: true|false
    """
    q = flask.request.args.get("q")
    tags = flask.request.args.getlist("tag") or None
    if not tags:
        tags_csv = flask.request.args.get("tags", "").strip()
        if tags_csv:
            tags = [t.strip() for t in tags_csv.split(",") if t.strip()]

    suite_id_params = flask.request.args.getlist("suite_id") or None
    suite_ids: Optional[List[int]] = None
    if suite_id_params:
        parsed_suite_ids: List[int] = []
        for raw_suite_id in suite_id_params:
            try:
                parsed_suite_ids.append(int(raw_suite_id))
            except ValueError:
                # игнорируем нечисловые значения
                continue
        if parsed_suite_ids:
            suite_ids = parsed_suite_ids

    suite_name = flask.request.args.get("suite_name")
    limit = flask.request.args.get("limit", const.TESTCASE_PER_PAGE_LIMIT)
    cursor = flask.request.args.get("cursor")
    sort = flask.request.args.get("sort", "-created_at")
    include_deleted = testcase_help.parse_bool_param(
        flask.request.args.get("include_deleted")
    )

    try:
        items, meta = testcase_help.get_test_cases_cursored(
            q=q,
            tags=tags,
            suite_ids=suite_ids,
            suite_name=suite_name,
            limit=limit,
            cursor=cursor,
            sort=sort,
            include_deleted=bool(include_deleted),
        )
    except testcase_help.ValidationError as ve:
        logger.warning("Ошибка валидации list_test_cases", exc_info=ve)
        flask.abort(400, description=str(ve))
    except Exception as e:
        logger.exception("Неожиданная ошибка в list_test_cases", exc_info=e)
        flask.abort(500, description="Ошибка базы данных")

    serialized = [testcase_help.serialize_test_case(tc) for tc in items]
    response = {"items": serialized, "meta": meta}
    return flask.jsonify(response)


@bp.route("/test_cases/<int:test_case_id>", methods=["GET"])
def get_test_case(test_case_id: int):
    """
    GET /test_cases/<id>

    Возвращает один TestCase по id.

    Поддерживает query-параметр:
      - include_deleted=true|false  (по умолчанию false)

    Ответы:
      - 200 OK + JSON — если найден
      - 400 Bad Request — если параметры неверны
      - 404 Not Found — если TestCase не найден (или удалён и include_deleted не установлен)
      - 500 Internal Server Error — при неизвестных ошибках БД
    """
    # Разбор optional-параметра include_deleted (string -> bool/None)
    include_deleted_param = testcase_help.parse_bool_param(
        flask.request.args.get("include_deleted")
    )
    include_deleted = bool(include_deleted_param)

    try:
        tc = testcase_help.get_test_case_by_id(
            test_case_id, include_deleted=include_deleted
        )
    except testcase_help.ValidationError as ve:
        logger.warning("Ошибка валидации при получении TestCase", exc_info=ve)
        flask.abort(400, description=str(ve))
    except testcase_help.NotFoundError as ne:
        logger.info("TestCase не найден", exc_info=ne)
        flask.abort(404, description=str(ne))
    except Exception as exc:
        logger.exception("Неожиданная ошибка при получении TestCase", exc_info=exc)
        flask.abort(500, description="Ошибка сервера")

    # Сериализуем и возвращаем
    body = testcase_help.serialize_test_case(tc)
    return flask.jsonify(body)


@bp.route("/test_cases/<int:test_case_id>", methods=["PUT", "POST"])
def update_test_case(test_case_id: int):
    """
    PUT /test_cases/<id>

    Полный апдейт TestCase. Ожидается JSON-представление (такие же поля, как для POST/create).
    Семантика: полный replace — клиент отправляет желаемое состояние.

    Ответы:
      - 200 OK + JSON (обновлённый объект) — при успехе
      - 400 Bad Request — ошибка валидации payload
      - 404 Not Found — тест-кейс не найден или помечен как удалённый
      - 409 Conflict — конфликт целостности (например дублирующееся имя)
      - 500 Internal Server Error — ошибки БД / прочие ошибки
    """

    logger.info("update_test_case: incoming request", test_case_id=test_case_id)
    payload = _get_test_case_payload()

    if not payload:
        logger.error("update_test_case: пустой или некорректный JSON")
        flask.abort(400, description="Invalid or missing JSON body")

    try:
        updated_tc = testcase_help.update_test_case_from_payload(test_case_id, payload)

    except testcase_help.ValidationError as ve:
        logger.warning("Ошибки валидации при обновлении TestCase", exc_info=ve)
        flask.abort(400, description=str(ve))

    except testcase_help.NotFoundError as ne:
        logger.info("TestCase не найден при попытке обновления", exc_info=ne)
        flask.abort(404, description=str(ne))

    except testcase_help.ConflictError as ce:
        logger.warning("Конфликт при обновлении TestCase", exc_info=ce)
        flask.abort(409, description=str(ce))

    except DatabaseError as dbe:
        db.session.rollback()
        logger.exception("Ошибка БД при обновлении TestCase", exc_info=dbe)
        flask.abort(500, description="Database error")

    except Exception as e:
        db.session.rollback()
        logger.exception("Непредвиденная ошибка при обновлении TestCase", exc_info=e)
        flask.abort(500, description="Unexpected error")

    body = testcase_help.serialize_test_case(updated_tc)
    if flask.request.accept_mimetypes.accept_html:
        # редирект обратно на страницу с выбранным кейсом
        return flask.redirect(
            flask.url_for("routes.test_cases_page", selected_id=test_case_id)
        )
    return flask.jsonify(body), 200


@bp.route("/test_cases/<int:test_case_id>", methods=["DELETE", "POST"])
def delete_test_case(test_case_id: int):
    """
    DELETE /test_cases/<id> — мягкое удаление (soft delete).
    Возвращает:
      - 204 No Content — удалено успешно
      - 404 Not Found — если TestCase не найден или уже удалён
      - 409 Conflict — ошибка целостности БД
      - 500 — прочие ошибки
    """
    logger.info("delete_test_case: incoming request", test_case_id=test_case_id)

    try:
        testcase_help.soft_delete_test_case(test_case_id)

    except testcase_help.ValidationError as ve:
        logger.warning("delete_test_case: ошибка валидации", exc_info=ve)
        flask.abort(400, description=str(ve))

    except testcase_help.NotFoundError as ne:
        logger.info("delete_test_case: TestCase не найден", exc_info=ne)
        flask.abort(404, description=str(ne))

    except testcase_help.ConflictError as ce:
        logger.warning("delete_test_case: конфликт при удалении", exc_info=ce)
        flask.abort(409, description=str(ce))

    except DatabaseError as dbe:
        db.session.rollback()
        logger.exception("delete_test_case: ошибка БД", exc_info=dbe)
        flask.abort(500, description="Database error")

    except Exception as e:
        db.session.rollback()
        logger.exception("delete_test_case: непредвиденная ошибка", exc_info=e)
        flask.abort(500, description="Unexpected error")

    # Успешно: ничего не возвращаем, редиректим на станицу с тест кейсами
    if flask.request.accept_mimetypes.accept_html:
        return flask.redirect(flask.url_for("routes.test_cases_page"))
    return "", 204


@bp.route("/test_cases/<int:test_case_id>/attachments", methods=["POST"])
def upload_test_case_attachment(test_case_id: int):
    """
    Загрузка одного файла в тест-кейс (multipart/form-data, field name 'file').
    Возвращает 201 + JSON (метаданные attachment).
    """
    if "file" not in flask.request.files:
        flask.abort(400, description="Файл обязателен")

    file_storage = flask.request.files["file"]
    if not file_storage or file_storage.filename == "":
        flask.abort(400, description="Файл обязателен")

    # проверим, что тест-кейс существует и не удалён
    tc = TestCase.query.get(test_case_id)
    if not tc or tc.is_deleted:
        flask.abort(404, description="TestCase не найден")

    # bucket по константе
    bucket = getattr(
        __import__("constants"),
        "TESTCASE_ATTACHMENTS_BUCKET_NAME",
        "testcase-attachments",
    )

    try:
        object_name, size = attach_help.upload_attachment_stream(
            test_case_id, file_storage, bucket
        )
    except Exception:
        logger.exception(
            "upload_test_case_attachment: upload failed",
            test_case_id=test_case_id,
            filename=file_storage.filename,
        )
        flask.abort(500, description="Storage upload failed")

    content_type = getattr(file_storage, "mimetype", None)
    try:
        attachment = attach_help.create_attachment_record_and_commit(
            test_case_id, file_storage.filename, object_name, bucket, content_type, size
        )
    except Exception:
        logger.exception(
            "upload_test_case_attachment: Ошибка базы данных при создании вложения",
            test_case_id=test_case_id,
            object_name=object_name,
        )
        flask.abort(500, description="Ошибка базы данных при создании вложения")

    body = attach_help.serialize_attachment(attachment)
    if flask.request.accept_mimetypes.accept_html:
        # редирект обратно на страницу где selected_case открыт
        return flask.redirect(
            flask.url_for("routes.test_cases_page", selected_id=test_case_id)
        )
    else:
        return flask.jsonify(body), 201


@bp.route("/test_cases/<int:test_case_id>/attachments", methods=["GET"])
def list_test_case_attachments(test_case_id: int):
    tc = TestCase.query.get(test_case_id)
    if not tc:
        flask.abort(404, description="TestCase не найден")

    items = attach_help.list_attachments_for_test_case(test_case_id)
    return flask.jsonify({"items": items}), 200


@bp.route(
    "/test_cases/<int:test_case_id>/attachments/<int:attachment_id>", methods=["GET"]
)
def get_test_case_attachment(test_case_id: int, attachment_id: int):
    """
    Если ?download=1 — проксируем (stream) файл из MinIO, выставляя Content-Disposition (filename + filename*).
    Иначе возвращаем метаданные.
    """
    attachment = Attachment.query.get(attachment_id)
    if not attachment or attachment.test_case_id != test_case_id:
        flask.abort(404, description="Вложение не найдено")

    download_mode = flask.request.args.get("download")
    if download_mode in ("1", "true", "True"):
        # stream через сервер
        try:
            stream_generator = attach_help.stream_attachment_generator(attachment)
        except Exception:
            logger.exception(
                "get_test_case_attachment: ошибка чтения хранилища",
                attachment_id=attachment_id,
                test_case_id=test_case_id,
            )
            flask.abort(500, description="ошибка чтения хранилища")

        filename = (
            attachment.original_filename or attachment.object_name or "attachment"
        )
        cd_value = attach_help.make_content_disposition(
            filename
        )  # можно вызвать локально или inline
        headers = {"Content-Disposition": cd_value}
        if attachment.size:
            headers["Content-Length"] = str(int(attachment.size))

        return flask.Response(
            stream_generator,
            content_type=attachment.content_type or "application/octet-stream",
            headers=headers,
            direct_passthrough=True,
        )

    # non-download -> метаданные
    body = {
        "id": attachment.id,
        "original_filename": attachment.original_filename,
        "object_name": attachment.object_name,
        "bucket": attachment.bucket,
        "content_type": attachment.content_type,
        "size": int(attachment.size) if attachment.size is not None else None,
        "created_at": (
            attachment.created_at.isoformat() if attachment.created_at else None
        ),
        "download_path": f"/test_cases/{test_case_id}/attachments/{attachment.id}?download=1",
    }
    return flask.jsonify(body), 200


@bp.route("/test_cases/<int:test_case_id>/attachments/archives", methods=["GET"])
def get_archives_for_test_case(test_case_id: int):
    tc = TestCase.query.get(test_case_id)
    if not tc:
        flask.abort(404, description="TestCase не найден")

    items = attach_help.list_archives_for_test_case(test_case_id)
    return flask.jsonify({"items": items}), 200


@bp.route(
    "/test_cases/<int:test_case_id>/attachments/<int:attachment_id>",
    methods=["DELETE", "POST"],
)
def delete_test_case_attachment(test_case_id: int, attachment_id: int):
    logger.info(
        "delete_test_case_attachment: incoming request",
        test_case_id=test_case_id,
        attachment_id=attachment_id,
    )

    attachment = Attachment.query.get(attachment_id)
    if not attachment or attachment.test_case_id != test_case_id:
        flask.abort(404, description="Вложение не найдено")

    try:
        attach_help.delete_attachment_by_object(attachment)
    except Exception:
        db.session.rollback()
        logger.exception(
            "delete_test_case_attachment: не удалось удалить объект или удалить запись в базе данных",
            attachment_id=attachment_id,
            test_case_id=test_case_id,
        )
        flask.abort(500, description="Не удалось удалить вложение.")

    logger.info(
        "delete_test_case_attachment: удалено",
        attachment_id=attachment_id,
        test_case_id=test_case_id,
    )
    if flask.request.accept_mimetypes.accept_html:
        # редирект обратно на страницу тест кейса, чтобы фронт обновился
        return flask.redirect(
            flask.url_for("routes.test_cases_page", selected_id=test_case_id)
        )
    return "", 204


@bp.route("/testcases", methods=["GET"])
def test_cases_page():
    # Параметры фильтра/страницы
    q = flask.request.args.get("q", "").strip()
    suite_name = flask.request.args.get("suite_name", "").strip()
    suite_id = flask.request.args.get("suite_id")
    sort = flask.request.args.get("sort", "-created_at")
    cursor = flask.request.args.get("cursor")
    include_deleted = testcase_help.parse_bool_param(
        flask.request.args.get("include_deleted")
    )

    # поддерживаем форматы для тегов:
    #   ?tags=one,two
    #   ?tags=one&tags=two
    raw_tags = []
    try:
        # getlist вернёт все повторяющиеся params, если есть
        raw_list = flask.request.args.getlist("tags")
        for entry in raw_list:
            if not entry:
                continue
            # разбираем CSV внутри каждого entry
            for tag in entry.split(","):
                tag = tag.strip()
                if tag:
                    raw_tags.append(tag)
    except Exception:
        raw_tags = []

    # уникализируем, сохраняя порядок
    seen = set()
    tags = []
    for tag in raw_tags:
        if tag not in seen:
            seen.add(tag)
            tags.append(tag)

    # получить кейсы (через существующий helper)
    try:
        # get_test_cases_cursored ожидает suite_ids либо None
        suite_ids = None
        if suite_id:
            try:
                suite_ids = [int(suite_id)]
            except Exception:
                suite_ids = None

        items, meta = testcase_help.get_test_cases_cursored(
            q=q,
            tags=tags or None,
            suite_ids=suite_ids,
            suite_name=suite_name or None,
            limit=flask.request.args.get("limit", const.TESTCASE_PER_PAGE_LIMIT),
            cursor=cursor,
            sort=sort,
            include_deleted=bool(include_deleted),
        )
    except Exception:
        items = []
        meta = {}

    # подготовка suites (список для левого сайдбара)
    try:
        from app.models import Tag, TestSuite

        suites_q = TestSuite.query.filter_by(is_deleted=False)
        if suite_name:
            # фильтр по имени suite (ILike чтобы поиск был нечувствителен к регистру)
            suites_q = suites_q.filter(TestSuite.name.ilike(f"%{suite_name}%"))
        suites = suites_q.order_by(TestSuite.name).all()

        # подготовим список всех тегов для dropdown на фронте (если модель Tag есть)
        try:
            # если у вас есть флаг is_deleted для Tag — используйте его
            all_tags = Tag.query.order_by(Tag.name).all()
        except Exception:
            # fallback: если Tag нет / не поддерживает .order_by
            all_tags = []
    except Exception:
        suites = []
        all_tags = []

    # selected_case (если нужно показать подробности)
    selected_case = None
    selected_id = flask.request.args.get("selected_id")
    if selected_id:
        try:
            selected_case = testcase_help.get_test_case_by_id(
                int(selected_id), include_deleted=bool(include_deleted)
            )
        except Exception:
            selected_case = None

    create_flag = flask.request.args.get("create") in ("1", "true", "True")

    return flask.render_template(
        "test_cases.html",
        cases=items,
        meta=meta,
        suites=suites,
        selected_case=selected_case,
        create=create_flag,
        all_tags=all_tags,  # <- список тегов для фронта
        selected_tags=",".join(tags) if tags else "",
    )
