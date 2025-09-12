from typing import List, Optional

from flask import (Blueprint, Response, abort, jsonify, render_template,
                   request, url_for)
from sqlalchemy.exc import DatabaseError
from werkzeug.routing import BuildError

import constants as const
from app import db
from app.clients import MinioClient
from app.models import TestResult
from helpers import testrun_helpers
from helpers.testcase_helpers import (ConflictError, NotFoundError,
                                      ValidationError,
                                      create_test_case_from_payload,
                                      get_test_case_by_id,
                                      get_test_cases_cursored,
                                      parse_bool_param, serialize_test_case)
from logger import init_logger

bp = Blueprint("routes", __name__)
minio_client = MinioClient()
logger = init_logger()


@bp.route("/", methods=["GET"])
@bp.route("/index", methods=["GET"])
@bp.route("/index/", methods=["GET"])
def home():
    """
    Домашняя страница
    """
    response = render_template(const.TEMPLATE_INDEX)
    logger.info("Обработан запрос на главную страницу")
    return response


@bp.route("/health", methods=["GET"])
def health_check():
    response = jsonify({"status": "ok"})
    logger.info("Обработан запрос на проверку доступности")
    return response


@bp.route("/upload", methods=["POST"])
def upload_results():
    """
    API-метод для загрузки файлов и создания тестового запуска
    """
    try:
        # Шаг 1. Получаем файлы из запроса и проверяем их наличие
        files = request.files.getlist("files")
        if not files or all(f.filename == "" for f in files):
            logger.error("Необходимо загрузить хотя бы один файл")
            abort(400, description="Необходимо загрузить хотя бы один файл")

        # Проверка размера файлов
        testrun_helpers.check_files_size(files)

        # Шаг 2. Создаем временную запись о запуске автотестов в БД
        new_result = testrun_helpers.create_temporary_test_result()
        logger.info("Создана новая временная запись о запуске автотестов")

    except DatabaseError as error_msg:
        # Откат транзакций в случае ошибки при работе с БД
        db.session.rollback()
        logger.exception("Ошибка при создании записи в базе данных или директории")
        abort(500, description=error_msg)

    # Шаг 3. Анализируем файлы и извлекаем параметры запуска автотестов
    try:
        test_run_info = testrun_helpers.check_all_tests_passed_run(files)
        if not test_run_info:
            logger.error("Не удалось извлечь параметры тестрана")
            abort(400, description="Ошибка анализа файлов")
    except Exception as error_msg:
        logger.exception("Неизвестная ошибка при анализе тестрана")
        abort(500, description=error_msg)

    # Шаг 4. Формируем уникальное имя для запуска автотестов и обновляем данные в БД
    try:
        testrun_helpers.update_test_result(new_result, test_run_info)
        logger.info(f"Обновлены данные тестрана с ID: {new_result.id}")
    except DatabaseError as error_msg:
        # Откат транзакций в случае исключения
        db.session.rollback()
        logger.exception("Ошибка при сохранении статуса тестрана в базу данных")
        abort(500, description=error_msg)

    # Шаг 5. Обрабатываем файлы и обновляем ссылку на них в БД
    success_files = []
    error_files = []
    logger.info("Загрузка файлов в Minio", run_name=new_result.run_name)
    for file in files:
        if not file or not testrun_helpers.allowed_file(file.filename):
            logger.error(f"Недопустимый файл: {file.filename}")
            error_files.append(file.filename)
            continue  # Пропуск недопустимого файла и продолжение обработки

        try:
            successful_filename = testrun_helpers.process_and_upload_file(
                new_result.run_name, file
            )
            if successful_filename:
                success_files.append(successful_filename)
        except (testrun_helpers.DatabaseError, OSError) as file_error:
            logger.exception(f"Ошибка обработки файла {file.filename}: {file_error}")
            db.session.rollback()
            error_files.append(file.filename)

    # Лог итогового статуса обработки файлов
    if success_files:
        logger.info(f"Успешно загруженные файлы в MinIO: {', '.join(success_files)}")
    if error_files:
        logger.warning(f"Ошибка обработки следующих файлов: {', '.join(error_files)}")
        abort(500, description="Некоторые файлы не были успешно обработаны")

    response = jsonify({"run_id": new_result.id, "message": "Файлы успешно загружены"})
    response_code = 201
    logger.info("Файлы успешно загружены", status_code=response_code)
    return response, response_code


@bp.route("/reports", methods=["GET"])
def get_reports():
    """
    Возвращает страницу со списком отчетов
    """
    results = testrun_helpers.fetch_reports()
    testrun_helpers.log_reports(results)
    return render_template(const.TEMPLATE_REPORTS, results=results)


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
    return Response(html_content, mimetype="text/html")


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
        response = jsonify({"message": "TestRun помечен как удаленный"})
        logger.info("Успешное удаление TestRun", run_id=run_id)
        return response
    else:
        error_msg = "TestRun не найден"
        logger.error(error_msg, run_id=run_id)
        abort(404, description=error_msg)


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
    payload = request.get_json(silent=True)
    if not payload:
        logger.error("create_test_case: пустой или некорректный JSON")
        abort(400, description="Invalid or missing JSON body")

    try:
        # Всю логику создания в helper — там транзакция и валидация
        tc = create_test_case_from_payload(payload)

    except ValidationError as ve:
        # Ошибки валидации входных данных -> 400 Bad Request
        logger.warning(
            "Ошибки валидации входных данных при создании TestCase", exc_info=ve
        )
        abort(400, description=str(ve))

    except NotFoundError as ne:
        # Ссылка на несуществующий Tag/Suite -> 404 Not Found
        logger.warning(
            "Ссылка на несуществующий Tag/Suite при создании TestCase", exc_info=ne
        )
        abort(404, description=str(ne))

    except ConflictError as ce:
        # Конфликт целостности (например уникальное имя) -> 409 Conflict
        logger.warning("Конфликт при создании TestCase", exc_info=ce)
        abort(409, description=str(ce))

    except DatabaseError as dbe:
        # Ошибки БД — откатываем сессию и возвращаем 500
        db.session.rollback()
        logger.exception("Ошибка БД при создании TestCase", exc_info=dbe)
        abort(500, description="Ошибка базы данных")

    except Exception as e:
        # Непредвиденные ошибки — откат и 500
        db.session.rollback()
        logger.exception("Непредвиденная ошибка при создании TestCase", exc_info=e)
        abort(500, description="Неожиданная ошибка")

    # Успех — сериализуем и возвращаем 201 Created с локой
    body = serialize_test_case(tc)
    try:
        # Пытаемся сформировать URL через именованный роут get_test_case
        location = url_for("routes.get_test_case", id=tc.id)
    except BuildError:
        # Если детального роутa ещё нет — используем fallback путь
        location = f"/test_cases/{tc.id}"

    response = jsonify(body)
    return response, 201, {"Location": location}


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
    q = request.args.get("q")
    tags = request.args.getlist("tag") or None

    suite_id_params = request.args.getlist("suite_id") or None
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

    suite_name = request.args.get("suite_name")
    limit = request.args.get("limit", const.TESTCASE_PER_PAGE_LIMIT)
    cursor = request.args.get("cursor")
    sort = request.args.get("sort", "-created_at")
    include_deleted = parse_bool_param(request.args.get("include_deleted"))

    try:
        items, meta = get_test_cases_cursored(
            q=q,
            tags=tags,
            suite_ids=suite_ids,
            suite_name=suite_name,
            limit=limit,
            cursor=cursor,
            sort=sort,
            include_deleted=bool(include_deleted),
        )
    except ValidationError as ve:
        logger.warning("Ошибка валидации list_test_cases", exc_info=ve)
        abort(400, description=str(ve))
    except Exception as e:
        logger.exception("Неожиданная ошибка в list_test_cases", exc_info=e)
        abort(500, description="Ошибка базы данных")

    serialized = [serialize_test_case(tc) for tc in items]
    response = {"items": serialized, "meta": meta}
    return jsonify(response)


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
    include_deleted_param = parse_bool_param(request.args.get("include_deleted"))
    include_deleted = bool(include_deleted_param)

    try:
        tc = get_test_case_by_id(test_case_id, include_deleted=include_deleted)
    except ValidationError as ve:
        logger.warning("Ошибка валидации при получении TestCase", exc_info=ve)
        abort(400, description=str(ve))
    except NotFoundError as ne:
        logger.info("TestCase не найден", exc_info=ne)
        abort(404, description=str(ne))
    except Exception as exc:
        logger.exception("Неожиданная ошибка при получении TestCase", exc_info=exc)
        abort(500, description="Ошибка сервера")

    # Сериализуем и возвращаем
    body = serialize_test_case(tc)
    return jsonify(body)
