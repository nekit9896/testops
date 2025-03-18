from datetime import datetime

from flask import (
    Blueprint,
    abort,
    jsonify,
    render_template,
    request,
    send_from_directory,
)
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

@bp.route('/', methods=['GET'] )
@bp.route('/index', methods=['GET'] )
@bp.route('/index/', methods=['GET'] )
def home():
    """
    Домашняя страница
    """
    response = render_template(const.TEMPLATE_INDEX)
    logger.info("Обработан запрос на главную страницу")
    return response

@bp.route('/health', methods=['GET'] )
def health_check():
    response = jsonify({"status": "ok"})
    logger.info("Обработан запрос на проверку доступности")
    return response

@bp.route('/upload', methods=['POST'] )
def upload_results():
    """
    API-метод для загрузки файлов и создания тестового запуска
    """
    try:
        # Шаг 1. Получаем файлы из запроса и проверяем их наличие
        files = request.files.getlist("files")
        if not files or all(f.filename == '' for f in files):
            logger.error("Необходимо загрузить хотя бы один файл")
            abort(400, description="Необходимо загрузить хотя бы один файл")

        # Шаг 2. Создаем временную запись о запуске автотестов в БД
        new_result = helpers.create_temporary_test_result()
        logger.info("Создана новая временная запись о запуске автотестов")

    except DatabaseError as error_msg:
        # Откат транзакций в случае ошибки при работе с БД
        db.session.rollback()
        logger.exception("Ошибка при создании записи в базе данных или директории")
        abort(500, description=error_msg)

    # Шаг 3. Анализируем файлы и извлекаем параметры запуска автотестов
    test_run_info = helpers.check_all_tests_passed_run(files)

    try:
        # Шаг 4. Формируем уникальное имя для запуска автотестов и обновляем данные в БД
        helpers.update_test_result(new_result, test_run_info)
        logger.info("Создана новая постоянная запись о запуске автотестов")
    except DatabaseError as error_msg:
        # Откат транзакций в случае исключения
        db.session.rollback()
        logger.exception("Ошибка при сохранении статуса тест рана в базу данных")
        abort(500, description=error_msg)

    try:
        # Шаг 5. Создаем папку для сохранения файлов на сервере
        helpers.create_result_directory(new_result.run_name)
        logger.info("Создана директория для сохранения результатов")
    except Exception as error_msg:
        logger.exception("Ошибка при создании директории для результатов")
        abort(500, description=error_msg)

    try:
        # Шаг 6. Обрабатываем файлы и обновляем ссылку на них в БД
        for file in files:
            if file and helpers.allowed_file(file.filename):
                helpers.process_and_upload_file(new_result.run_name, file)

        file_link = f"{minio_client.minio_endpoint}/{const.ALLURE_RESULTS_BUCKET_NAME}/{new_result.run_name}"
        # Обновляем file_link в PostgreSQL
        new_result.file_link = file_link
        db.session.commit()
    except (DatabaseError, OSError) as error_msg:
        error_msg = (
            "Ошибка при обработке файлов или обновлении ссылки на файл в базе данных"
        )
        logger.exception(error_msg)
        abort(500, description=error_msg)
    response = jsonify({"run_id": new_result.id, "message": "Файлы успешно загружены"})
    response_code = 201
    logger.info("Файлы успешно загружены", status_code=response_code)
    return response, response_code


@bp.route("/reports", methods=["GET"])
def get_reports():
    """
    Возвращает страницу со списком отчетов
    """
    # Получает имена директорий с отчетами
    result_names = helpers.create_reports_list()
    reports = []
    # Для каждого прогона заполняем словарь
    if result_names:
        for name in result_names:
            # Здесь потребуется подключение к базе и данные о прогоне будем подтягивать из базы
            reports.append(
                {
                    "id": 0,
                    "name": name,
                    "date": datetime.now().isoformat(),
                    "status": "success",
                }
            )
        response = render_template(const.TEMPLATE_REPORTS, reports=reports)
        logger.info("Обработан запрос на страницу списка отчетов", status_code=200)
        return response
    # Если отсутствуют результаты прогонов, то будет выведен пустой список отчетов
    if not result_names:
        response = render_template(const.TEMPLATE_REPORTS, reports=[])
        logger.info(
            "Обработан запрос на страницу списка отчетов, список отчетов пуст",
            status_code=200,
        )
    return response


@bp.route("/reports/<int:result_id>", methods=["GET"])
def view_report(result_id: int):
    """
    Открывает отчет
    """
    # Получает название директории с отчетом по id
    result_dir_name = str(result_id)
    # Получает директорию, в которой находится html отчет
    report_dir = helpers.get_report(result_dir_name)

    response = send_from_directory(report_dir, const.ALLURE_REPORT_NAME)
    logger.info(
        "Обработан запрос на страницу с отчетом", status_code=200, result_id=result_id
    )
    return response


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
