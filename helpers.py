import json
import os
import subprocess
from datetime import datetime

from flask import current_app
from werkzeug.utils import secure_filename

import constants as const
from app import db
from app.clients import MinioClient
from app.models import TestResult

minio_client = MinioClient()


def allowed_file(filename):
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in const.ALLOWED_EXTENSIONS
    )


def get_project_subdir_path(folder_name: str) -> str:
    """
    Получает путь к папке в корне проекта
    """
    return os.path.join(os.getcwd(), folder_name)


def check_report_exist(report_dir: str) -> bool:
    """
    Проверяет наличие отчета.
    """
    report_path = os.path.join(report_dir, const.ALLURE_REPORT_NAME)
    return os.path.isfile(report_path)


def get_folder_names(directory: str) -> list[str]:
    """
    Возвращает список названий папок в указанной директории.
    """
    return [
        name
        for name in os.listdir(directory)
        if os.path.isdir(os.path.join(directory, name))
    ]


def create_reports_list():
    """Функция получения списка отчетов."""
    # Получает путь к директории с отчетами
    results_folder_path = get_project_subdir_path(const.ALLURE_RESULTS_FOLDER_NAME)
    # Получает имена директорий с отчетами
    result_names = get_folder_names(results_folder_path)
    return result_names


def generate_report(result_dir_path: str, report_dir_path: str) -> None:
    """
    Создает html-версию отчета командой в консоли.
    """
    command = [
        "allure",
        "generate",
        result_dir_path,
        "-o",
        report_dir_path,
        "--clean",
        "-c",
        "--single-file",
    ]
    try:
        subprocess.run(command, shell=True, text=True, check=True)

    except subprocess.CalledProcessError as error:
        raise RuntimeError(
            f"Ошибка при генерации Allure-отчета: Код {error.returncode}\n"
            f"Вывод ошибки: {error.stderr.strip() if error.stderr else 'Нет вывода ошибки'}"
        )


def get_report(result_dir_name: str) -> str:
    """
    Получает директорию, в которой находится html отчет
    """
    # Получает путь к папке с результатами прогонов
    results_dir_path = get_project_subdir_path(const.ALLURE_RESULTS_FOLDER_NAME)
    # Получает путь к папке с отчетами
    reports_dir_path = get_project_subdir_path(const.ALLURE_REPORT_FOLDER_NAME)
    # Получает путь к папке с результатами конкретного прогона
    result_dir_path = os.path.join(results_dir_path, result_dir_name)
    # Получает путь к папке с html отчетом
    report_dir_path = os.path.join(reports_dir_path, result_dir_name)

    # Проверяет наличие отчета
    if check_report_exist(report_dir_path):
        return report_dir_path

    else:
        # Создает html версию отчета командой в консоли
        generate_report(result_dir_path, report_dir_path)

        if check_report_exist(report_dir_path):
            return report_dir_path

        else:
            raise FileNotFoundError("Ошибка при получении html файла с отчетом")


def process_and_upload_file(run_name, file):
    try:
        filename = secure_filename(file.filename)
        file_path = f"{run_name}/{filename}"

        # Открываем поток файла без сохранения на диск
        file_stream = file.stream
        content_length = len(file.read())
        file.stream.seek(0)  # Сбрасываем указатель после подсчета длины

        # Проверяем что бакет существует
        minio_client.ensure_bucket_exists(const.ALLURE_RESULT_BUCKET_NAME)

        # Загрузка файла в MinIO
        minio_client.put_object(
            bucket_name=const.ALLURE_RESULT_BUCKET_NAME,
            file_path=file_path,
            file_stream=file_stream,
            content_length=content_length,
        )
    except Exception as e:
        current_app.logger.error(f"Error processing file {file.filename}: {str(e)}")
        raise


def parse_json_file(file):
    """Парсит содержимое файла и возвращает json данные."""
    try:
        content = file.read().decode(const.ENCODING)
        return json.loads(content)
    except Exception as e:
        current_app.logger.error(f"Ошибка при чтении файла {file.filename}: {str(e)}")
        return None


def format_timestamp(timestamp):
    """Форматирует временную метку в миллисекундах в строку по заданному формату."""
    return datetime.fromtimestamp(timestamp / const.TIMESTAMP_DIVISOR).strftime(
        const.DATE_FORMAT
    )


def check_all_tests_passed_run(files):
    status = const.STATUS_PASS
    start_time, stop_time = None, None

    for file in files:
        if file.filename.endswith(const.RESULT_NAMING):
            data = parse_json_file(file)
            if (
                data is None
                or const.STATUS_KEY not in data
                or data[const.STATUS_KEY] != const.STATUS_PASS
            ):
                status = const.STATUS_FAIL

        elif file.filename.endswith(const.CONTAINER_NAMING):
            data = parse_json_file(file)
            if data:
                start_time = data.get(const.START_RUN_KEY)
                stop_time = data.get(const.STOP_RUN_KEY)

    # Конвертация времени из миллисекунд в нужный формат
    start_time_str = format_timestamp(start_time) if start_time else None
    stop_time_str = format_timestamp(stop_time) if stop_time else None

    return {
        const.STATUS_KEY: status,
        const.START_RUN_KEY: start_time_str,
        const.STOP_RUN_KEY: stop_time_str,
    }


def create_temporary_test_result():
    """Создает временную запись в БД с тестовым запуском."""
    new_result = TestResult(
        run_name=f"{const.DEFAULT_RUN_NAME}_{datetime.now()}",
        start_date="",
        end_date="",
        status="",
        file_link="",
    )
    db.session.add(new_result)
    db.session.commit()  # Коммитим временную запись
    return new_result


def update_test_result(new_result, test_run_info):
    """Обновляет параметры тестового запуска в БД."""
    run_id = new_result.id
    run_name = f"run_{run_id}_{test_run_info.get(const.START_RUN_KEY)}"
    new_result.run_name = run_name
    new_result.status = test_run_info.get(const.STATUS_KEY)
    new_result.start_date = test_run_info.get(const.START_RUN_KEY)
    new_result.end_date = test_run_info.get(const.STOP_RUN_KEY)
    db.session.commit()


def create_result_directory(run_name):
    """Создает директорию для сохранения файлов тестового запуска."""
    result_folder = os.path.join(const.UPLOAD_FOLDER, run_name)
    os.makedirs(result_folder, exist_ok=True)
