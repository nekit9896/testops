from flask import Blueprint, Response, abort, jsonify, render_template, request
from sqlalchemy.exc import DatabaseError

import constants as const
import helpers
from app import db
from app.clients import MinioClient
from app.models import TestResult
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
        helpers.check_files_size(files)

        # Шаг 2. Создаем временную запись о запуске автотестов в БД
        new_result = helpers.create_temporary_test_result()
        logger.info("Создана новая временная запись о запуске автотестов")

    except DatabaseError as error_msg:
        # Откат транзакций в случае ошибки при работе с БД
        db.session.rollback()
        logger.exception("Ошибка при создании записи в базе данных или директории")
        abort(500, description=error_msg)

    # Шаг 3. Анализируем файлы и извлекаем параметры запуска автотестов
    try:
        test_run_info = helpers.check_all_tests_passed_run(files)
        if not test_run_info:
            logger.error("Не удалось извлечь параметры тестрана")
            abort(400, description="Ошибка анализа файлов")
    except Exception as error_msg:
        logger.exception("Неизвестная ошибка при анализе тестрана")
        abort(500, description=error_msg)

    # Шаг 4. Формируем уникальное имя для запуска автотестов и обновляем данные в БД
    try:
        helpers.update_test_result(new_result, test_run_info)
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
        if not file or not helpers.allowed_file(file.filename):
            logger.error(f"Недопустимый файл: {file.filename}")
            error_files.append(file.filename)
            continue  # Пропуск недопустимого файла и продолжение обработки

        try:
            successful_filename = helpers.process_and_upload_file(
                new_result.run_name, file
            )
            if successful_filename:
                success_files.append(successful_filename)
        except (helpers.DatabaseError, OSError) as file_error:
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
    results = helpers.fetch_reports()
    helpers.log_reports(results)
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
        helpers.log_and_abort(result_id, testrun)

    run_name = testrun.run_name

    # Проверка существования бакета
    minio_client.ensure_bucket_exists(const.ALLURE_REPORTS_BUCKET_NAME)

    # Получение или генерация allure-report
    html_file = helpers.get_or_generate_report(run_name)

    # Возвращает HTML как ответ
    html_content = html_file.read().decode("utf-8")
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
