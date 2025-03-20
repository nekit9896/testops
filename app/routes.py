from datetime import datetime

from flask import (Blueprint, current_app, jsonify, render_template, request,
                   send_from_directory)

import constants as const
import helpers
from app import db
from app.clients import MinioClient
from app.models import TestResult

bp = Blueprint("routes", __name__)
minio_client = MinioClient()


@bp.route("/health", methods=["GET"])
def health_check():
    return jsonify({"status": "ok"}), 200


@bp.route("/upload", methods=["POST"])
def upload_results():
    """API-метод для загрузки файлов и создания тестового запуска."""
    try:
        # Шаг 1. Получаем файлы из запроса и проверяем их наличие
        files = request.files.getlist("files")
        if not files or all(f.filename == "" for f in files):
            return jsonify({"error": "Необходимо загрузить хотя бы один файл"}), 400

        # Шаг 2. Создаем временную запись о запуске автотестов в БД
        new_result = helpers.create_temporary_test_result()

    except Exception as e:
        # Откат транзакции и логирование ошибки при работе с БД
        db.session.rollback()
        current_app.logger.error(f"Ошибка при создании записи базы данных: {str(e)}")
        return jsonify({"error": "Ошибка обработки данных"}), 500

    # Шаг 3. Анализируем файлы и извлекаем параметры запуска автотестов
    test_run_info = helpers.check_all_tests_passed_run(files)

    try:
        # Шаг 4. Формируем уникальное имя для запуска автотестов и обновляем данные в БД
        helpers.update_test_result(new_result, test_run_info)
    except Exception as e:
        # Логируем ошибку и откатываем транзакцию в случае исключения
        db.session.rollback()
        current_app.logger.error(
            f"Ошибка при сохранении статуса тест рана в базу данных: {str(e)}"
        )
        return jsonify({"error": "Ошибка обработки данных"}), 500

    try:
        # Шаг 5. Создаем папку для сохранения файлов на сервере
        helpers.create_result_directory(new_result.run_name)
    except OSError as e:
        current_app.logger.error(
            f"Ошибка при создании директории для результатов: {str(e)}"
        )
        return (
            jsonify({"error": "Ошибка при создании директории для сохранения файлов"}),
            500,
        )

    try:
        # Шаг 6. Обрабатываем файлы и обновляем ссылку на них в БД
        for file in files:
            if file and helpers.allowed_file(file.filename):
                helpers.process_and_upload_file(new_result.run_name, file)

        file_link = f"{minio_client.minio_endpoint}/{const.ALLURE_RESULT_BUCKET_NAME}/{new_result.run_name}"
        # Обновляем file_link в PostgreSQL
        new_result.file_link = file_link
        db.session.commit()
    except Exception as e:
        current_app.logger.error(f"Ошибка при обработке файлов: {str(e)}")
        return (
            jsonify(
                {
                    "error": "Ошибка при обработке файлов или обновлении ссылки на файл в базе данных"
                }
            ),
            500,
        )

    return jsonify({"run_id": new_result.id, "message": "Файлы успешно загружены"}), 201


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
    result_names = helpers.create_reports_list()
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
    report_dir = helpers.get_report(result_dir_name)
    try:
        return send_from_directory(report_dir, const.ALLURE_REPORT_NAME), 200

    except FileNotFoundError:
        return jsonify({"error": "Нет такого отчета"}), 404

    except Exception as error:
        return jsonify({"error": str(error)}), 500


@bp.route("/delete_test_run/<int:run_id>", methods=["DELETE"])
def delete_test_run(run_id):
    """
    Маркирует тестран как удаленный по run_id.
    ORM (Object-Relational Mapping), в нашем случае SQLAlchemy, позволяет обращаться к базе данных так,
    будто это обычный Python-объект.
    Метод получает объект TestResult по его первичному ключу (run_id),
    и если объект существует, он помечает его как удаленный (is_deleted = True)
    и сохраняет изменения в базе данных.
    """
    test_result = TestResult.query.get(run_id)

    if test_result:
        test_result.is_deleted = True
        db.session.commit()
        return jsonify({"message": "TestRun помечен как удаленный"}), 200
    else:
        return jsonify({"message": "TestRun не найден"}), 404
