import datetime
import io
import json
import os
import shutil
import subprocess
import tempfile
from typing import Any, Dict, List, Optional, Sequence, Tuple

import flask
from flask import abort
from minio import S3Error
from sqlalchemy import inspect
from sqlalchemy.exc import DatabaseError
from werkzeug.datastructures import FileStorage

import constants as const
from app import db
from app.clients import MinioClient
from app.models import TestResult
from helpers.allure_utils import extract_stand_from_environment_file
from logger import init_logger

minio_client = MinioClient()
logger = init_logger()


def get_request_files() -> List[FileStorage]:
    """Возвращает список валидных файлов из запроса."""
    files = flask.request.files.getlist("files")
    valid_files = [file for file in files if file and file.filename]
    if not valid_files:
        logger.error("Необходимо загрузить хотя бы один файл")
        flask.abort(400, description="Необходимо загрузить хотя бы один файл")
    return valid_files


def create_temp_test_result() -> TestResult:
    """Создает временную запись TestResult или завершает запрос с ошибкой."""
    try:
        new_result = create_temporary_test_result()
        logger.info("Создана новая временная запись о запуске автотестов")
        return new_result
    except DatabaseError as error_msg:
        db.session.rollback()
        logger.exception("Ошибка при создании записи в базе данных")
        flask.abort(500, description=str(error_msg))


def extract_test_run_info(files: Sequence[FileStorage]):
    """Анализирует файлы и возвращает информацию о тестране."""
    try:
        test_run_info = check_all_tests_passed_run(files)
        if not test_run_info:
            logger.error("Не удалось извлечь параметры тестрана")
            flask.abort(400, description="Ошибка анализа файлов")
        return test_run_info
    except Exception as error_msg:
        logger.exception("Неизвестная ошибка при анализе тестрана")
        flask.abort(500, description=str(error_msg))


def upload_all_files(
    run_name: str, files: Sequence[FileStorage]
) -> Tuple[List[str], List[str]]:
    """Загружает файлы и разделяет их на успешные/ошибочные."""
    success_files: List[str] = []
    error_files: List[str] = []
    minio_client.ensure_bucket_exists(const.ALLURE_RESULTS_BUCKET_NAME)

    for file in files:
        filename = file.filename or "unknown"
        if not allowed_file(filename):
            logger.error("Недопустимый файл: %s", filename)
            error_files.append(filename)
            continue

        try:
            uploaded = process_and_upload_file(run_name, file)
            success_files.append(uploaded)
        except (DatabaseError, OSError, ValueError) as file_error:
            logger.exception("Ошибка обработки файла %s: %s", filename, file_error)
            db.session.rollback()
            error_files.append(filename)

    return success_files, error_files


def get_existing_run_or_abort(result_id: int) -> TestResult:
    """Возвращает TestResult или завершает запрос, если запись недоступна."""
    testrun = TestResult.query.get(result_id)
    log_and_abort(result_id, testrun)
    return testrun


def _validate_upload_file(file: FileStorage) -> str:
    """Убедиться, что объект файла пригоден для дальнейшей обработки."""
    if not file or not file.filename:
        raise ValueError("Файл отсутствует или поврежден.")
    return file.filename


def _read_file_content(file: FileStorage) -> bytes:
    """Считывает и валидирует содержимое файла."""
    file.seek(0)
    content = file.read()
    if not content:
        raise ValueError(f"Файл {file.filename} пустой и не будет загружен.")
    return content


def _extract_stand_value(filename: str, file_content: bytes) -> Optional[str]:
    """Пытается извлечь stand из environment.properties."""
    if filename != "environment.properties":
        return None

    try:
        content_text = file_content.decode("utf-8", errors="ignore")
    except Exception:
        logger.exception(
            "Не удалось декодировать environment.properties для извлечения stand"
        )
        return None

    stand = extract_stand_from_environment_file(content_text) or None
    return stand.strip() if stand else None


def _persist_detected_stand(run_name: str, detected_stand: str) -> None:
    """Сохраняет значение stand в TestResult, если запись существует."""
    try:
        test_result: Optional[TestResult] = TestResult.query.filter_by(
            run_name=run_name, is_deleted=False
        ).first()
        if not test_result:
            logger.warning(
                "Не удалось найти TestResult для run_name=%s, stand=%s не сохранён",
                run_name,
                detected_stand,
            )
            return

        test_result.stand = detected_stand
        db.session.add(test_result)
        db.session.commit()
        logger.info(
            "Сохранили stand='%s' для run=%s в TestResult(id=%s)",
            detected_stand,
            run_name,
            test_result.id,
        )
    except Exception:
        logger.exception(
            "Ошибка при сохранении stand=%s для run=%s в базе данных",
            detected_stand,
            run_name,
        )


def _upload_file_to_minio(run_name: str, filename: str, file_content: bytes) -> None:
    """Загружает файл в MinIO."""
    file_path = f"{run_name}/{filename}"
    file_stream = io.BytesIO(file_content)
    minio_client.ensure_bucket_exists(const.ALLURE_RESULTS_BUCKET_NAME)
    minio_client.put_object(
        bucket_name=const.ALLURE_RESULTS_BUCKET_NAME,
        file_path=file_path,
        file_stream=file_stream,
        content_length=len(file_content),
    )


def _safe_int(value: Optional[int]) -> Optional[int]:
    """Безопасно преобразует значение к int."""
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _status_indicates_failure(status: Optional[str]) -> bool:
    """Возвращает True, если значение статуса сигнализирует о неуспехе."""
    if not status:
        return False
    return str(status).lower() != const.STATUS_PASS


def _steps_contain_failure(steps: Optional[Sequence[dict]]) -> bool:
    """Рекурсивно проверяет шаги на наличие статусов отличных от passed."""
    if not steps:
        return False

    for step in steps:
        if _status_indicates_failure(step.get(const.STATUS_KEY)):
            return True
        if _steps_contain_failure(step.get("steps")):
            return True
    return False


def _result_contains_failure(data: dict) -> bool:
    """Проверяет результат теста на наличие любых неуспешных статусов."""
    if _status_indicates_failure(data.get(const.STATUS_KEY)):
        return True

    if _steps_contain_failure(data.get("steps")):
        return True

    for section in ("befores", "afters"):
        for entry in data.get(section, []):
            if _status_indicates_failure(entry.get(const.STATUS_KEY)):
                return True
            if _steps_contain_failure(entry.get("steps")):
                return True

    return False


def allowed_file(filename: str) -> bool:
    """
    По точке находим расширение файла и проверяем на соответствие списка разрешенных в ALLOWED_EXTENSIONS
    """
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in const.ALLOWED_EXTENSIONS
    )


def process_and_upload_file(run_name: str, file: FileStorage) -> str:
    """
    Валидирует, обрабатывает и загружает файл в MinIO.
    Пытается извлечь stand из environment.properties и сохранить его в БД.
    """
    try:
        filename = _validate_upload_file(file)
        logger.info("Тип файла: %s, имя файла: %s", type(file), filename)

        file_content = _read_file_content(file)
        logger.info("Размер файла %s: %s байт", filename, len(file_content))

        detected_stand = _extract_stand_value(filename, file_content)
        if detected_stand:
            logger.info(
                "Обнаружен stand='%s' в environment.properties для run=%s",
                detected_stand,
                run_name,
            )

        _upload_file_to_minio(run_name, filename, file_content)

        if detected_stand:
            _persist_detected_stand(run_name, detected_stand)

        return filename

    except OSError:
        logger.exception("Ошибка обработки файла", filename=file.filename)
        raise


def parse_json_file(file: Any) -> Optional[dict]:
    """Парсит содержимое файла и возвращает json данные."""
    try:
        content = file.read().decode(const.ENCODING)
        return json.loads(content)
    except json.JSONDecodeError:
        logger.exception("Ошибка при чтении файла", filename=file.filename)
        return None


def format_timestamp(timestamp: int) -> str:
    """Форматирует временную метку в миллисекундах в строку по заданному формату."""
    return datetime.datetime.fromtimestamp(
        timestamp / const.TIMESTAMP_DIVISOR
    ).strftime(const.DB_DATE_FORMAT)


def check_all_tests_passed_run(
    files: Sequence[FileStorage],
) -> dict[str, Optional[str]]:
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
            - const.STATUS_KEY: Статус выполнения тестов ('passed' или 'fail').
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
    status = const.STATUS_PASS
    logger.info("Проверка статусов автотестов внутри данного отчета")

    result_start_times: list[int] = []
    result_stop_times: list[int] = []
    container_start_ms: Optional[int] = None
    container_stop_ms: Optional[int] = None

    for file in files:
        filename = getattr(file, "filename", "") or ""
        if filename.endswith(const.RESULT_NAMING):
            data = parse_json_file(file)

            if not data:
                status = const.STATUS_FAIL
                logger.warning("Файл %s не содержит валидный JSON", filename)
            else:
                if _result_contains_failure(data):
                    status = const.STATUS_FAIL
                    logger.info("В файле %s обнаружены неуспешные шаги", filename)

                start_ms = _safe_int(data.get(const.START_RUN_KEY))
                stop_ms = _safe_int(data.get(const.STOP_RUN_KEY))
                if start_ms is not None:
                    result_start_times.append(start_ms)
                if stop_ms is not None:
                    result_stop_times.append(stop_ms)

        elif filename.endswith(const.CONTAINER_NAMING):
            data = parse_json_file(file)
            if data:
                container_start_ms = _safe_int(data.get(const.START_RUN_KEY))
                container_stop_ms = _safe_int(data.get(const.STOP_RUN_KEY))

    if container_start_ms is None and result_start_times:
        container_start_ms = min(result_start_times)
    if container_stop_ms is None and result_stop_times:
        container_stop_ms = max(result_stop_times)

    start_time_str = (
        format_timestamp(container_start_ms) if container_start_ms else None
    )
    stop_time_str = format_timestamp(container_stop_ms) if container_stop_ms else None

    logger.info(
        "Итоговый статус тестов: %s, start=%s, stop=%s",
        status,
        start_time_str,
        stop_time_str,
    )

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


def update_test_result(new_result: "TestResult", test_run_info: dict) -> None:
    """Обновляет параметры тестового запуска в БД."""
    run_id = new_result.id
    run_name = f"run_{run_id}_{test_run_info.get(const.START_RUN_KEY)}"
    new_result.run_name = run_name
    new_result.status = test_run_info.get(const.STATUS_KEY)
    new_result.start_date = test_run_info.get(const.START_RUN_KEY)
    new_result.end_date = test_run_info.get(const.STOP_RUN_KEY)
    db.session.commit()


def check_files_size(files: List, max_size: int = None) -> bool:
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


def _format_datetime(value: Optional[datetime.datetime]) -> Optional[str]:
    if not value:
        return None
    return value.strftime(const.VIEW_DATE_FORMAT)


def _serialize_test_result(result: TestResult) -> Dict[str, Any]:
    """Приводит TestResult к словарю для фронтенда."""
    return {
        "id": result.id,
        "run_name": result.run_name,
        "start_date": _format_datetime(result.start_date),
        "end_date": _format_datetime(result.end_date),
        "stand": result.stand or None,
        "status": result.status,
    }


def _has_older_runs(oldest_id: int) -> bool:
    """Проверяет наличие более старых записей по id."""
    return (
        TestResult.query.filter(
            TestResult.is_deleted.is_(False), TestResult.id < oldest_id
        )
        .order_by(TestResult.id.desc())
        .limit(1)
        .first()
        is not None
    )


def _has_newer_runs(newest_id: int) -> bool:
    """Проверяет наличие более новых записей по id."""
    return (
        TestResult.query.filter(
            TestResult.is_deleted.is_(False), TestResult.id > newest_id
        )
        .order_by(TestResult.id.asc())
        .limit(1)
        .first()
        is not None
    )


def fetch_reports(
    cursor: Optional[int],
    limit: int,
    direction: str = "next",
) -> Dict[str, Any]:
    """
    Возвращает страницу отчетов с курсорной пагинацией.
    direction: 'next' (старее) или 'prev' (новее).
    """
    if direction not in {"next", "prev"}:
        raise ValueError("Направление должно быть либо 'next' или 'prev'")

    base_query = TestResult.query.filter_by(is_deleted=False)
    if cursor:
        if direction == "next":
            base_query = base_query.filter(TestResult.id < cursor)
        else:
            base_query = base_query.filter(TestResult.id > cursor)

    order_column = TestResult.id.desc()
    if direction == "prev":
        order_column = TestResult.id.asc()

    results = base_query.order_by(order_column).limit(limit + 1).all()
    has_more_in_direction = len(results) > limit
    items = results[:limit]

    if direction == "prev":
        items = list(reversed(items))

    serialized = [_serialize_test_result(item) for item in items]

    if not items:
        return {
            "items": [],
            "next_cursor": None,
            "prev_cursor": None,
            "has_next": False,
            "has_prev": False,
        }

    newest_id = items[0].id
    oldest_id = items[-1].id

    has_prev = _has_newer_runs(newest_id)
    has_next = _has_older_runs(oldest_id)

    # Обновляем флаги, учитывая результат текущего запроса
    if direction == "next" and cursor:
        has_prev = True
    if direction == "prev":
        has_next = True
        if not has_more_in_direction:
            has_prev = False

    return {
        "items": serialized,
        "next_cursor": oldest_id if has_next else None,
        "prev_cursor": newest_id if has_prev else None,
        "has_next": has_next,
        "has_prev": has_prev,
    }


def log_reports(results_present: bool) -> None:
    """Логирует состояние страницы отчётов."""
    if results_present:
        logger.info("Обработан запрос на страницу списка отчетов", status_code=200)
    else:
        logger.info(
            "Обработан запрос на страницу списка отчетов, список отчетов пуст",
            status_code=200,
        )


def generate_and_upload_report(run_name: str) -> None:
    """
    Генерирует и загружает allure-report в MinIO.
    Аргумент run_name - название тест-рана, используемое для директории allure-result и allure-report.
    """
    temp_dir = tempfile.mkdtemp()  # Создаем временную директорию для результатов
    report_dir = tempfile.mkdtemp()  # Создаем временную директорию для отчёта

    try:
        logger.info("Начало скачивания файлов из MinIO")
        download_allure_results(run_name, temp_dir)

        logger.info("Начало генерации allure-report")
        generate_allure_report(temp_dir, report_dir)

        logger.info("Загрузка allure-report в MinIO")
        upload_report_to_minio(run_name, report_dir)

    finally:
        logger.info("Очистка временных директорий")
        cleanup_temporary_directories([temp_dir, report_dir])


def download_allure_results(
    allure_results_directory: str, destination_dir: str
) -> None:
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
        if os.path.exists(file_path):
            logger.info(
                f"Файл {file_path} загружен, размер: {os.path.getsize(file_path)} байт"
            )
        else:
            logger.error(f"Ошибка: Файл {file_path} не загружен")


def generate_allure_report(result_dir_path: str, report_dir_path: str) -> None:
    """
    Генерирует Allure-отчёт на основе результатов тестов.
    На основе предоставленной директории с результатами тестов, функция выполняет
    системную команду для генерации HTML-отчёта в указанной директории. В случае
    ошибки генерации, логируется сообщение об ошибке и выбрасывается исключение.

    result_dir_path - путь к директории, содержащей результаты тестов allure-results.
    report_dir_path - путь к директории, куда будет сохранен HTML-отчёт Allure
    """
    command = (
        f"allure generate {result_dir_path} "
        f"-o {report_dir_path} --clean --single-file"
    )
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
        raise RuntimeError("Не удалось сгенерировать Allure-отчёт") from error


def upload_report_to_minio(run_name: str, report_dir: str) -> None:
    """
    Загружает HTML-отчёт Allure в MinIO.
    run_name - ммя тест-запуска для файла allure-report.
    report_dir - путь к временной директории, где находится HTML-отчёт.
    """
    final_report_file = os.path.join(report_dir, "index.html")
    with open(final_report_file, "rb") as file:
        minio_client.ensure_bucket_exists(const.ALLURE_REPORTS_BUCKET_NAME)
        minio_client.put_object(
            const.ALLURE_REPORTS_BUCKET_NAME,
            f"{run_name}.html",
            file,
            os.path.getsize(final_report_file),
        )


def cleanup_temporary_directories(directories: list) -> None:
    """
    Удаляет указанные временные директории.
    """
    for directory in directories:
        if os.path.exists(directory):
            shutil.rmtree(directory)
            logger.info(f"Временная директория {directory} удалена")


def report_exists(run_name: str) -> bool:
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


def log_and_abort(result_id: int, testrun) -> None:
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
