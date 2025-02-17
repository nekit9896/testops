import os
from datetime import datetime

from flask import (Blueprint, current_app, jsonify, render_template, request,
                   send_from_directory)

from app import db
from app.clients import MinioClient
from app.models import TestResult
from constants import (ALLURE_REPORT_NAME, BUCKET_NAME, DATE_FORMAT,
                       UPLOAD_FOLDER)
from helpers import (allowed_file, check_all_tests_passed_run,
                     create_reports_list, get_report, process_and_upload_file)

bp = Blueprint("routes", __name__)
minio_client = MinioClient()


@bp.route("/health", methods=["GET"])
def health_check():
    return jsonify({"status": "ok"}), 200


@bp.route("/upload", methods=["POST"])
def upload_results():
    try:
        # Получаем файлы из запроса
        files = request.files.getlist("files")
        if not files or all(f.filename == "" for f in files):
            return jsonify({"error": "Необходимо загрузить хотя бы один файл"}), 400

        # Создаем запись в БД с временным run_name
        default_run_name = "TempName"
        new_result = TestResult(
            run_name=default_run_name,
            start_date=datetime.now(),
            status="pending",
            file_link="",  # Временно пусто, так как ссылки пока нет
        )
        db.session.add(new_result)
        db.session.commit()  # Коммитим первый этап работы с БД

        # Получаем сгенерированный run_id и формируем run_name
        run_id = new_result.id
        # run_id = TEMP_RUN_ID
        timestamp = datetime.now().strftime(DATE_FORMAT)
        run_name = f"run_{run_id}_{timestamp}"

        # Обновляем run_name в БД
        new_result.run_name = run_name
        db.session.commit()  # Коммитим обновление run_name
    except Exception as e:
        db.session.rollback()  # Откат транзакции при любой ошибке в работе с БД
        current_app.logger.error(f"Ошибка при создании записи базы данных: {str(e)}")
        return jsonify({"error": "Ошибка при создании записи в базе данных"}), 500

    # Операции с файловой системой
    try:
        # Создаем папку для сохранения результатов
        result_folder = os.path.join(UPLOAD_FOLDER, run_name)
        os.makedirs(result_folder, exist_ok=True)
    except OSError as e:
        current_app.logger.error(
            f"Ошибка при создании директории для результатов: {str(e)}"
        )
        return (
            jsonify({"error": "Ошибка при создании директории для сохранения файлов"}),
            500,
        )

    # Определяем общий статус тест рана
    status = check_all_tests_passed_run(files)

    try:
        new_result.status = status
        db.session.commit()
    except Exception as e:
        # Логируем ошибку и откатываем транзакцию в случае исключения
        db.session.rollback()
        current_app.logger.error(
            f"Ошибка при сохранении статуса тест рана в базу данных: {str(e)}"
        )
        return jsonify({"error": "Ошибка обработки данных"}), 500

    try:
        # Сохраняем файлы
        for file in files:
            if file and allowed_file(file.filename):
                process_and_upload_file(run_name, file)

        file_link = f"{minio_client.minio_endpoint}/{BUCKET_NAME}/{run_name}"

        # Обновляем file_link в PostgreSQL
        new_result.file_link = file_link
        db.session.commit()
    except Exception as e:
        current_app.logger.error(
            f"Ошибка при обработке файлов или обновлении ссылки на файл в базе данных: {str(e)}"
        )
        return (
            jsonify(
                {
                    "error": "Ошибка при обработке файлов или обновлении ссылки на файл в базе данных"
                }
            ),
            500,
        )

    return jsonify({"run_id": run_id, "message": "Файлы успешно загружены"}), 201


@bp.route(rule="/", methods=["GET"])
@bp.route(rule="/index", methods=["GET"])
@bp.route(rule="/index/", methods=["GET"])
def home():
    """
    Домашняя страница
    """
    try:
        return render_template("index.html"), 200

    except Exception as error:
        return jsonify({"error": str(error)}), 500


@bp.route(rule="/reports", methods=["GET"])
def get_reports():
    """
    Возвращает страницу со списком отчетов
    """
    # Получает имена директорий с отчетами
    result_names = create_reports_list()
    reports = []
    # Для каждого прогона заполняем словарь
    if result_names:
        for name in result_names:
            # Здесь требуется подключение к базе и данные о прогоне будем подтягивать из базы
            reports.append(
                {
                    "id": 0,
                    "name": name,
                    "date": datetime.now().isoformat(),
                    "status": "success",
                }
            )

        return (
            render_template(template_name_or_list="reports.html", reports=reports),
            200,
        )
    # Если отсутствуют результаты прогонов, то будет выведен пустой список отчетов
    if not result_names:
        return (
            render_template(template_name_or_list="reports.html", reports=reports),
            200,
        )

    else:
        return jsonify({"error": "Ошибка при получении списка отчетов"}), 500


@bp.route(rule="/reports/<int:result_id>", methods=["GET"])
def view_report(result_id: int):
    """
    Открывает отчет
    """
    # Получает название директории с отчетом по id
    result_dir_name = str(result_id)
    # Получает директорию, в которой находится отчет
    report_dir = get_report(result_dir_name)
    try:
        return send_from_directory(report_dir, ALLURE_REPORT_NAME), 200

    except FileNotFoundError:
        return jsonify({"error": "Нет такого отчета"}), 404

    except Exception as error:
        return jsonify({"error": str(error)}), 500
