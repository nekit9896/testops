import os
from datetime import datetime

from flask import (Blueprint, jsonify, render_template, request,
                   send_from_directory)
from werkzeug.utils import secure_filename

from app import db
from app.models import TestRun
from constants import ALLURE_REPORT_NAME, UPLOAD_FOLDER
from helpers import allowed_file, create_reports_list, get_report

bp = Blueprint("routes", __name__)


@bp.route("/health", methods=["GET"])
def health_check():
    return jsonify({"status": "ok"}), 200


@bp.route("/upload", methods=["POST"])
def upload_results():
    # Проверяем обязательное поле run_name
    run_name = request.form.get("run_name")
    if not run_name:
        return jsonify({"error": "Поле run_name обязательно"}), 400

    # Получаем файлы из запроса
    files = request.files.getlist("files")
    if not files or all(f.filename == "" for f in files):
        return jsonify({"error": "Необходимо загрузить хотя бы один файл"}), 400

    # Создаем уникальную папку для прогонов
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    folder_name = f"run_{run_name}_{timestamp}"
    result_folder = os.path.join(UPLOAD_FOLDER, folder_name)
    os.makedirs(result_folder, exist_ok=True)

    # Сохраняем файлы
    for file in files:
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file_path = os.path.join(result_folder, filename)
            file.save(file_path)

    # Создаем запись о прогоне в базе данных
    test_run = TestRun(run_name=run_name, result_folder=result_folder)
    db.session.add(test_run)
    db.session.commit()

    return jsonify({"run_id": test_run.id, "message": "Файлы успешно загружены"}), 201


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
