import datetime
import json
import os
import subprocess

from sqlalchemy import inspect
from sqlalchemy.exc import DatabaseError
from werkzeug.utils import secure_filename

import constants as const
from app import db
from app.clients import MinioClient
from app.models import TestResult
from logger import init_logger

minio_client = MinioClient()
logger = init_logger()


def allowed_file(filename):
    """
    По точке находим расширение файла и проверяем на соответствие списка разрешенных в ALLOWED_EXTENSIONS
    """
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in const.ALLOWED_EXTENSIONS
    )


def valid_files(files):
    """Проверка на наличие и валидность файлов"""
    return files and not all(f.filename == "" for f in files)


def save_files(run_name, files):
    """Сохраняет файлы в базе данных."""
    logger.info("Сохранение файлов отчета в БД", run_name=run_name)
    try:
        for file in files:
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                file_content = file.read()

                test_run = TestResult(
                    run_name=run_name, file_name=filename, file_content=file_content
                )
                db.session.add(test_run)

        db.session.commit()

    except (DatabaseError, OSError):
        logger.exception("Ошибка при сохранении файлов отчета в БД", run_name=run_name)


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
    """
    Функция получения списка отчетов
    """
    # Получает путь к директории с отчетами
    results_folder_path = get_project_subdir_path(const.ALLURE_RESULT_FOLDER_NAME)
    # Получает имена директорий с отчетами
    result_names = get_folder_names(results_folder_path)
    return result_names


def generate_report(result_dir_path: str, report_dir_path: str) -> None:
    """
    Создает html версию отчета командой в консоли.
    """
    command = [
        "allure",
        "generate",
        result_dir_path,
        "-o",
        report_dir_path,
        "--clean",
        "--single-file",
    ]
    try:
        logger.info("Создание html версии отчета")
        subprocess.run(command, shell=True, text=True, check=True)

    except subprocess.CalledProcessError as error:
        error_msg = (
            error.stderr.strip()
            if error.stderr
            else "Нет вывода ошибки выполнения команды"
        )
        logger.exception(
            "Ошибка при генерации Allure-отчета",
            description=error_msg,
            error_code=error.returncode,
        )
        raise RuntimeError


def get_report(result_dir_name: str) -> str:
    """
    Получает директорию, в которой находится html отчет
    """
    # Получает путь к папке с результатами прогонов
    results_dir_path = get_project_subdir_path(const.ALLURE_RESULT_FOLDER_NAME)
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
            error_msg = "Ошибка при получении html файла с отчетом"
            logger.error(error_msg, run_name=result_dir_path)
            raise FileNotFoundError(error_msg)


def process_and_upload_file(run_name, file):
    logger.info("Загрузка файлов в Minio", run_name=run_name)
    try:
        filename = secure_filename(file.filename)
        file_path = f"{run_name}/{filename}"

        # Считываем поток файла без сохранения на диск
        file_stream = file.stream
        content_length = len(file.read())
        file.stream.seek(0)  # Сбрасываем указатель после подсчета длины

        # Убеждаемся, что бакет существует
        minio_client.ensure_bucket_exists(const.ALLURE_RESULTS_BUCKET_NAME)

        # Загрузка файла в MinIO
        minio_client.put_object(
            bucket_name=const.ALLURE_RESULTS_BUCKET_NAME,
            file_path=file_path,
            file_stream=file_stream,
            content_length=content_length,
        )

    except OSError:
        logger.exception("Ошибка обработки файла", filename=file.filename)
        raise


def parse_json_file(file):
    """Парсит содержимое файла и возвращает JSON данные."""
    try:
        content = file.read().decode(const.ENCODING)
        return json.loads(content)
    except json.JSONDecodeError:
        logger.exception("Ошибка при чтении файла", filename=file.filename)
        return None


def format_timestamp(timestamp):
    """Форматирует временную метку в миллисекундах в строку по заданному формату."""
    return datetime.datetime.fromtimestamp(
        timestamp / const.TIMESTAMP_DIVISOR
    ).strftime(const.DATE_FORMAT)


def check_all_tests_passed_run(files):
    """
    Проверяет, прошли ли все автотесты успешно, и возвращает статус,
    а также время начала и окончания выполнения тестов.

    Метод анализирует список файлов, содержащих результаты выполнения автотестов,
    и определяет общий статус тестирования. Если хотя бы один тест не прошел успешно,
    статус тестрана будет установлен как 'fail'. Время начала и окончания тестов определяется
    либо из контейнерного файла, если он присутствует, либо из файлов с результатами,
    если контейнерный файл отсутствует.

    Параметры:
        files (list): Список файлов, содержащих результаты выполнения автотестов.
                      Каждый элемент списка должен иметь атрибут 'filename', который
                      используется для идентификации типа файла.

    Возвращает:
        dict: Словарь с ключами и значениями:
            - const.STATUS_KEY: Статус выполнения тестов ('success' или 'fail').
            - const.START_RUN_KEY: Время начала выполнения тестов в строковом формате
              (или None, если время не определено).
            - const.STOP_RUN_KEY: Время окончания выполнения тестов в строковом формате
              (или None, если время не определено).

    Обработка:
        - Инициализирует переменные для статуса тестов и времени начала/окончания.
        - Перебирает файлы и анализирует их содержимое.
        - Если файл является результатом выполнения тестов, проверяет статус и извлекает
          временные метки.
        - Если файл является контейнером, извлекает время начала и окончания.
        - В случае отсутствия контейнера, использует минимальное и максимальное время
          из файлов с результатами.
        - Конвертирует временные метки в строковый формат.
        - Возвращает словарь с итоговыми данными.
    """
    # Инициализируем переменную статуса теста(ов)
    status = const.STATUS_PASS
    # Инициализируем переменные для хранения времени начала и окончания запуска автотестов
    start_time, stop_time = None, None

    logger.info("Проверка статусов автотестов внутри данного отчета")

    # Инициализируем временные переменные для поиска минимального start и максимального stop
    result_start_times = []
    result_stop_times = []

    # Итерация по списку файлов для анализа их содержимого
    container_data_exists = False
    for file in files:
        # Обработка файлов с результатами выполнения тестов
        if file.filename.endswith(const.RESULT_NAMING):
            data = parse_json_file(file)

            # Если данные отсутствуют или статус тестов не соответствует success - изменяем статус на fail
            if not data or data.get(const.STATUS_KEY) != const.STATUS_PASS:
                status = const.STATUS_FAIL

            # Проверяем наличие ключей времени начала и остановки, если данные валидны
            if data:
                start_time = data.get(const.START_RUN_KEY, start_time)
                stop_time = data.get(const.STOP_RUN_KEY, stop_time)

        # Обработка контейнерного файла (если он присутствует)
        elif file.filename.endswith(const.CONTAINER_NAMING):
            data = parse_json_file(file)
            # Если данные существуют в контейнере, устанавливаем start_time и stop_time
            if data:
                container_data_exists = True
                start_time = data.get(const.START_RUN_KEY)
                stop_time = data.get(const.STOP_RUN_KEY)

    # Если контейнерный файл отсутствует, используем данные из result.json
    if not container_data_exists:
        if result_start_times:
            start_time = int(min(result_start_times))
        if result_stop_times:
            stop_time = int(max(result_stop_times))

    # Конвертируем время из миллисекунд в строковый формат
    start_time_str = format_timestamp(start_time) if start_time else None
    stop_time_str = format_timestamp(stop_time) if stop_time else None

    # Возвращаем результат времени начала и окончания тестирования
    return {
        const.STATUS_KEY: status,
        const.START_RUN_KEY: start_time_str,
        const.STOP_RUN_KEY: stop_time_str,
    }


def create_temporary_test_result():
    """
    Создает временную запись тестового результата в базе данных, при необходимости создавая соответствующую таблицу.

    Возвращает:
    - Объект `TestResult`, представляющий созданную запись о тестовом результате.

    Поведение:
    - Проверяет наличие таблицы `TestResult`. Если она не существует, создает её.
    - Создает новую запись `TestResult` с параметрами по умолчанию:
        - `run_name`: имя запуска формируется на основе константы `DEFAULT_RUN_NAME` и текущего времени.
        - `start_date`: `None`, так как результаты теста еще не распарсили.
        - `end_date`: `None`, так как результаты теста еще не распарсили.
        - `status`: устанавливается в `PENDING_STATUS`, показывая, что еще нет результата.
        - `file_link`: `None` изначально, поскольку ссылка на файл результата задается позже.
    - Добавляет новую запись в сеанс базы данных и сохраняет изменения.

    Исключения:
    - В случае ошибки базы данных, выполняет откат текущего сеанса и логирует ошибку,
    затем повторно вызывает исключение `DatabaseError`.
    """
    try:
        # Создаем таблицу, если она еще не создана
        inspector = inspect(db.engine)
        if not inspector.has_table(TestResult.__tablename__):
            db.create_all()

        # Создаем новый тестовый результат
        new_result = TestResult(
            run_name=f"{const.DEFAULT_RUN_NAME}_{datetime.datetime.now()}",
            start_date=None,
            end_date=None,
            status=const.PENDING_STATUS,
            file_link=None,
        )

        # Добавляем и коммитим новую запись
        db.session.add(new_result)
        db.session.commit()

        return new_result

    except DatabaseError as error_msg:
        # Обработка ошибки базы данных
        db.session.rollback()
        logger.exception("Ошибка при создании записи в базе данных", exc_info=error_msg)
        raise


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
