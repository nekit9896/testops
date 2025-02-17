import datetime
import json
import os
import subprocess

from flask import current_app
from werkzeug.utils import secure_filename

from app.clients import MinioClient
from constants import (ALLOWED_EXTENSIONS, ALLURE_REPORT_FOLDER_NAME,
                       ALLURE_REPORT_NAME, ALLURE_RESULT_FOLDER_NAME,
                       BUCKET_NAME, CONTAINER_NAMING, DATE_FORMAT, ENCODING,
                       RESULT_NAMING, START_RUN_KEY, STATUS_FAIL, STATUS_KEY,
                       STATUS_PASS, STOP_RUN_KEY, TIMESTAMP_DIVISOR)

minio_client = MinioClient()


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def get_project_subdir_path(folder_name: str) -> str:
    """
    Получает путь к папке в корне проекта
    """
    return os.path.join(os.getcwd(), folder_name)


def check_report_exist(report_dir: str) -> bool:
    """
    Проверяет наличие отчета.
    """
    report_path = os.path.join(report_dir, ALLURE_REPORT_NAME)
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
    results_folder_path = get_project_subdir_path(ALLURE_RESULT_FOLDER_NAME)
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
    results_dir_path = get_project_subdir_path(ALLURE_RESULT_FOLDER_NAME)
    # Получает путь к папке с отчетами
    reports_dir_path = get_project_subdir_path(ALLURE_REPORT_FOLDER_NAME)
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
        minio_client.ensure_bucket_exists(BUCKET_NAME)

        # Загрузка файла в MinIO
        minio_client.put_object(
            bucket_name=BUCKET_NAME,
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
        content = file.read().decode(ENCODING)
        return json.loads(content)
    except Exception as e:
        current_app.logger.error(f"Ошибка при чтении файла {file.filename}: {str(e)}")
        return None


def format_timestamp(timestamp):
    """Форматирует временную метку в миллисекундах в строку по заданному формату."""
    return datetime.datetime.fromtimestamp(timestamp / TIMESTAMP_DIVISOR).strftime(
        DATE_FORMAT
    )


def check_all_tests_passed_run(files):
    status = STATUS_PASS
    start_time, stop_time = None, None

    for file in files:
        if file.filename.endswith(RESULT_NAMING):
            data = parse_json_file(file)
            if (
                data is None
                or STATUS_KEY not in data
                or data[STATUS_KEY] != STATUS_PASS
            ):
                status = STATUS_FAIL

        elif file.filename.endswith(CONTAINER_NAMING):
            data = parse_json_file(file)
            if data:
                start_time = data.get(START_RUN_KEY)
                stop_time = data.get(STOP_RUN_KEY)

    # Конвертация времени из миллисекунд в нужный формат
    start_time_str = format_timestamp(start_time) if start_time else None
    stop_time_str = format_timestamp(stop_time) if stop_time else None

    return {
        STATUS_KEY: status,
        START_RUN_KEY: start_time_str,
        STOP_RUN_KEY: stop_time_str,
    }
