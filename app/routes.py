import os
from datetime import datetime

from flask import Blueprint, jsonify, request
from werkzeug.utils import secure_filename

from app import db
from app.models import TestRun
from constants import UPLOAD_FOLDER
from helpers import allowed_file

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
