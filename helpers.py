import datetime
import json
import os
import shutil
import subprocess
import tempfile

from flask import abort
from minio import S3Error
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


def generate_allure_report(result_dir_path: str, report_dir_path: str) -> None:
    """
    Генерирует Allure-отчёт на основе результатов тестов.
    На основе предоставленной директории с результатами тестов, функция выполняет
    системную команду для генерации HTML-отчёта в указанной директории. В случае
    ошибки генерации, логируется сообщение об ошибке и выбрасывается исключение.

    result_dir_path - путь к директории, содержащей результаты тестов allure-results.
    report_dir_path - путь к директории, куда будет сохранен HTML-отчёт Allure
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
        subprocess.run(command, shell=True, text=True, check=True)
    except subprocess.CalledProcessError as error:
        error_msg = (
            "Нет вывода ошибки выполнения команды"
            if not error.stderr
            else error.stderr.strip()
        )
        logger.exception(
            "Ошибка при генерации Allure-отчета",
            description=error_msg,
            error_code=error.returncode,
        )
        raise RuntimeError


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
    ).strftime(const.DB_DATE_FORMAT)


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


def check_files_size(files, max_size=None):
    """
    Проверка размера загружаемых файлов.
    files - список файлов для проверки.
    max_size - максимальный допустимый размер в байтах.
    """
    # Получение размера по умолчанию из переменной или установки стандартного 50 МБ
    if max_size is None:
        max_size = const.MAX_FILE_SIZE  # 50 MB по умолчанию

    # Считаем общий размер файлов
    total_size = 0
    for file in files:
        file.seek(0, 2)  # Переместить курсор в конец файла
        total_size += file.tell()  # Получить текущую позицию (размер в байтах)
        file.seek(0)  # Сбросить курсор на начало

    # Проверка превышения лимита
    if total_size > max_size:
        logger.error(
            "Общий размер загружаемых файлов превышен",
            total_size=total_size,
            max_size=max_size,
        )
        abort(400, description="Общий размер загружаемых файлов превышает допустимый")

    logger.info(
        "Размер файлов в пределах допустимого", total_size=total_size, max_size=max_size
    )
    return True


def fetch_reports():
    """
    Извлекает записи отчетов из базы данных и преобразует их в список словарей
    """
    test_results = (
        TestResult.query.filter_by(is_deleted=False)
        .order_by(TestResult.created_at.desc())
        .limit(20)
        .all()
    )
    return [
        {
            "id": result.id,
            "run_name": result.run_name,
            "start_date": (
                result.start_date.strftime(const.VIEW_DATE_FORMAT)
                if result.start_date
                else None
            ),
            "end_date": (
                result.end_date.strftime(const.VIEW_DATE_FORMAT)
                if result.end_date
                else None
            ),
            "status": result.status,
        }
        for result in test_results
    ]


def log_reports(results):
    """
    Логирует информацию о состоянии списка отчетов
    """
    if results:
        logger.info("Обработан запрос на страницу списка отчетов", status_code=200)
    else:
        logger.info(
            "Обработан запрос на страницу списка отчетов, список отчетов пуст",
            status_code=200,
        )


def generate_and_upload_report(run_name: str):
    """
    Генерирует и загружает allure-report в MinIO.
    Аргумент run_name - название тест-рана, используемое для директории allure-result и allure-report.
    """
    temp_dir = tempfile.mkdtemp()  # Создаем временную директорию для результатов
    report_dir = tempfile.mkdtemp()  # Создаем временную директорию для отчёта

    try:
        # Загружаем результаты из MinIO
        download_allure_results(run_name, temp_dir)

        # Генерируем Allure-отчёт
        generate_allure_report(temp_dir, report_dir)

        # Загружаем отчёт в MinIO
        upload_report_to_minio(run_name, report_dir)

    finally:
        # Очистка временных директорий
        cleanup_temporary_directories([temp_dir, report_dir])


def download_allure_results(allure_results_directory: str, destination_dir: str):
    """
    Загружает результаты Allure из MinIO в указанную директорию.
    Аргументы:
    allure_results_directory - директория в MinIO с allure-results.
    destination_dir - путь к локальной директории для сохранения allure-results.
    """
    for obj in minio_client.list_objects(
        const.ALLURE_RESULTS_BUCKET_NAME, prefix=f"{allure_results_directory}/"
    ):
        file_path = os.path.join(destination_dir, obj.object_name.split("/")[-1])
        minio_client.download_file(
            const.ALLURE_RESULTS_BUCKET_NAME, obj.object_name, file_path
        )


def upload_report_to_minio(run_name: str, report_dir: str):
    """
    Загружает HTML-отчёт Allure в MinIO.
    run_name - ммя тест-запуска для файла allure-report.
    report_dir - путь к временной директории, где находится HTML-отчёт.
    """
    final_report_file = os.path.join(report_dir, "index.html")
    with open(final_report_file, "rb") as file:
        minio_client.put_object(
            const.ALLURE_REPORTS_BUCKET_NAME,
            f"{run_name}.html",
            file,
            os.path.getsize(final_report_file),
        )


def cleanup_temporary_directories(directories: list):
    """
    Удаляет указанные временные директории.
    """
    for directory in directories:
        if os.path.exists(directory):
            shutil.rmtree(directory)


def report_exists(run_name: str):
    """
    Проверяет наличие отчёта Allure в хранилище MinIO.

    Данный метод используется для проверки существования HTML-отчета
    о тестировании с определённым именем в указанном бакете MinIO.
    Если отчёт существует, метод возвращает `True`, в противном
    случае – `False`.
    """
    try:
        minio_client.minio_client.stat_object(
            const.ALLURE_REPORTS_BUCKET_NAME, f"{run_name}.html"
        )
        return True
    except S3Error:
        return False


def log_and_abort(result_id: int, testrun):
    """
    Логирование и окончание запроса, если тестран не существует или помечен как удаленный.
    """
    if not testrun:
        logger.error(f"Test run с ID {result_id} не найден.")
        abort(404, description=f"Test run с ID {result_id} не найден.")

    if testrun.is_deleted:
        logger.warning(f"Test run {result_id} помечен как удаленный.")
        abort(404, description=f"Test run {testrun.run_name} помечен как удаленный.")


def get_or_generate_report(run_name: str):
    """
    Получение или генерация allure-report
    Загрузка allure-report в MinIO
    """
    if report_exists(run_name):
        return minio_client.minio_client.get_object(
            const.ALLURE_REPORTS_BUCKET_NAME, f"{run_name}.html"
        )
    generate_and_upload_report(run_name)
    return minio_client.minio_client.get_object(
        const.ALLURE_REPORTS_BUCKET_NAME, f"{run_name}.html"
    )
