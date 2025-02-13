import os
import subprocess

from minio import S3Error
from werkzeug.utils import secure_filename

from app import db
from app.models import TestResult
from app.clients import MinioClient
from constants import (ALLOWED_EXTENSIONS, ALLURE_REPORT_FOLDER_NAME,
                       ALLURE_REPORT_NAME, ALLURE_RESULT_FOLDER_NAME)

minio_client = MinioClient()

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def valid_files(files):
    """Проверка на наличие и валидность файлов."""
    return files and not all(f.filename == "" for f in files)


def save_files(run_name, files):
    """Сохраняет файлы в базе данных."""
    for file in files:
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file_content = file.read()

            test_run = TestResult(
                run_name=run_name, file_name=filename, file_content=file_content
            )
            db.session.add(test_run)

    db.session.commit()


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
