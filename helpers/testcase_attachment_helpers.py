import os
import tempfile
import urllib
from typing import Any, Dict, Generator, List, Optional, Tuple

from sqlalchemy.exc import IntegrityError
from werkzeug.datastructures import FileStorage

from app import db
from app.clients import MinioClient
from app.models import Attachment, TestCase
from constants import ATTACHMENTS_BUCKET

minio_client = MinioClient()
logger = __import__("logger").init_logger()


# -----------------------
# Вспомогательные функции
# -----------------------
def _get_content_length_from_filestorage(file_storage: FileStorage) -> Optional[int]:
    """
    Попытка аккуратно извлечь content-length из FileStorage или заголовков.
    Возвращает положительный int или None.
    """
    content_length = getattr(file_storage, "content_length", None)
    if content_length is None:
        headers = getattr(file_storage, "headers", None)
        content_length_header = headers.get("Content-Length") if headers else None
        if content_length_header:
            try:
                content_length = int(content_length_header)
            except Exception:
                content_length = None

    if content_length and int(content_length) > 0:
        try:
            return int(content_length)
        except Exception:
            return None
    return None


def make_content_disposition(filename: str) -> str:
    """
    Формирует Content-Disposition
    """
    filename_quoted = urllib.parse.quote(filename, safe="")
    return f"attachment; filename=\"{filename}\"; filename*=UTF-8''{filename_quoted}"


# -----------------------
# Основные хелперы (API)
# -----------------------
def upload_attachment_stream(
    test_case_id: int,
    file_storage: FileStorage,
    bucket_name: str = ATTACHMENTS_BUCKET,
) -> Tuple[str, int]:
    """
    Загружает attachment в MinIO и возвращает (object_name, size).
    Алгоритм:
      1) Попытка взять размер из content-length
      2) Если не удалось — попытка через stream.tell()/seek()
      3) Если не удалось — fallback: записать в tmp-файл и загрузить его
      4) Всегда передать корректный length в MinIO
    """
    if not file_storage or not file_storage.filename:
        raise ValueError("file_storage должен содержать filename")

    original_filename = file_storage.filename
    object_name = Attachment.make_object_name(test_case_id, original_filename)
    content_type = getattr(file_storage, "mimetype", None)

    stream = file_storage.stream
    temp_file_path: Optional[str] = None
    saved_stream_position: Optional[int] = None

    try:
        # 1) попытка взять Content-Length
        size = _get_content_length_from_filestorage(file_storage)

        # 2) попытка определить размер через seek/tell
        if size is None:
            try:
                saved_stream_position = stream.tell()
                stream.seek(0, os.SEEK_END)
                size = stream.tell()
                stream.seek(saved_stream_position)
                if size == 0:
                    size = None
            except Exception:
                size = None
                saved_stream_position = None

        # 3) если знаем size — проматываем в начало, иначе fallback
        if size is not None:
            try:
                stream.seek(0)
            except Exception:
                size = None

        if size is None:
            # fallback: записать во временный файл
            tmp_fd, temp_file_path = tempfile.mkstemp(prefix="attach_", suffix=".tmp")
            os.close(tmp_fd)
            total = 0
            try:
                try:
                    stream.seek(0)
                except Exception:
                    pass
                with open(temp_file_path, "wb") as write_file_handle:
                    while True:
                        chunk = stream.read(64 * 1024)
                        if not chunk:
                            break
                        write_file_handle.write(chunk)
                        total += len(chunk)
                size = total
            except Exception:
                # очистка tmp при ошибке
                if temp_file_path and os.path.exists(temp_file_path):
                    try:
                        os.unlink(temp_file_path)
                    except Exception:
                        logger.exception(
                            "upload_attachment_stream: ошибка удаления tmp при ошибке",
                            temp_file_path=temp_file_path,
                        )
                raise

            # загрузка из tmp файла
            with open(temp_file_path, "rb") as file_handle:
                minio_client.ensure_bucket_exists(bucket_name)
                minio_client.put_object(
                    bucket_name,
                    object_name,
                    file_handle,
                    size,
                    content_type=content_type,
                )
        else:
            # загрузка напрямую из потока
            minio_client.ensure_bucket_exists(bucket_name)
            minio_client.put_object(
                bucket_name, object_name, stream, size, content_type=content_type
            )

        logger.info(
            "upload_attachment_stream: uploaded",
            test_case_id=test_case_id,
            object_name=object_name,
            size=size,
            content_type=content_type,
        )
        return object_name, int(size)

    finally:
        # восстановим позицию потока, если возможно
        try:
            if saved_stream_position is not None:
                try:
                    stream.seek(saved_stream_position)
                except Exception:
                    logger.debug(
                        "upload_attachment_stream: ошибка восстановления позиции потока"
                    )
        except Exception:
            logger.debug(
                "upload_attachment_stream: логика восстановления позиции не сработала"
            )

        # удаляем временный файл, если он был создан
        if temp_file_path:
            try:
                os.unlink(temp_file_path)
            except Exception:
                logger.exception(
                    "upload_attachment_stream: не удалось удалить tmp",
                    temp_file_path=temp_file_path,
                )


def create_attachment_record_and_commit(
    test_case_id: int,
    original_filename: str,
    object_name: str,
    bucket: str,
    content_type: Optional[str],
    size: Optional[int],
) -> Attachment:
    """
    Создаёт запись Attachment в БД и коммитит.
    При IntegrityError — откат и попытка удалить объект из MinIO (best-effort), затем проброс ошибки.
    """
    attachment = Attachment(
        test_case_id=test_case_id,
        original_filename=original_filename,
        object_name=object_name,
        bucket=bucket,
        content_type=content_type,
        size=size,
    )
    db.session.add(attachment)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        logger.exception(
            "attachments_helpers: DB commit не удалось прикрепить",
            test_case_id=test_case_id,
            object_name=object_name,
        )
        # удаление объекта из minio (best-effort)
        try:
            minio_client.remove_object(bucket, object_name)
        except Exception:
            logger.exception(
                "attachments_helpers: удаление объекта из minio не удалось",
                object_name=object_name,
            )
        raise

    logger.info(
        "attachments_helpers: запись вложения создана",
        attachment_id=attachment.id,
        test_case_id=test_case_id,
    )
    return attachment


def serialize_attachment(attachment: Attachment) -> Dict:
    """
    Сериализация Attachment -> dict для API.
    """
    return {
        "id": attachment.id,
        "original_filename": attachment.original_filename,
        "object_name": attachment.object_name,
        "bucket": attachment.bucket,
        "content_type": attachment.content_type,
        "size": int(attachment.size) if attachment.size is not None else None,
        "created_at": (
            attachment.created_at.isoformat() if attachment.created_at else None
        ),
    }


def stream_attachment_generator(
    attachment: Attachment, chunk_size: int = 32 * 1024
) -> Generator[bytes, None, None]:
    """
    Возвращает генератор байт для передачи в Flask Response, прочитанный из MinIO.
    Клиент должен сформировать заголовки (Content-Disposition и Content-Length) сам.
    """
    response_obj = minio_client.get_object_stream(
        attachment.bucket, attachment.object_name
    )
    try:
        for chunk in response_obj.stream(chunk_size):
            yield chunk
    finally:
        try:
            response_obj.close()
        except Exception:
            pass


def list_attachments_for_test_case(test_case_id: int) -> List[Dict]:
    """
    Возвращает список сериализованных вложений для тест-кейса.
    (Просто маппинг записей в БД -> dict)
    """
    tc = TestCase.query.get(test_case_id)
    if not tc:
        return []
    return [serialize_attachment(a) for a in tc.attachments]


def list_archives_for_test_case(test_case_id: int) -> List[Dict]:
    """
    Возвращает список всех вложений для указанного тест-кейса.
    Каждый элемент — словарь с полями:
      - id: int
      - original_filename: str | None
      - size: int | None
      - download_path: относительный путь для скачивания через API (строка)

    Если тест-кейс не найден, возвращается пустой список.
    """
    tc = TestCase.query.get(test_case_id)
    if not tc:
        return []

    attachments: List[Dict[str, Any]] = []
    for attachment in tc.attachments:
        attachments.append(
            {
                "id": attachment.id,
                "original_filename": attachment.original_filename,
                "size": int(attachment.size) if attachment.size is not None else None,
                "download_path": f"/test_cases/{test_case_id}/attachments/{attachment.id}?download=1",
            }
        )
    return attachments


def delete_attachment_by_object(attachment: Attachment) -> None:
    """
    Удаляет attachment: сначала из MinIO, затем удаляет запись из БД.
    """
    # удаляем из MinIO
    minio_client.remove_object(attachment.bucket, attachment.object_name)

    # удаляем запись из БД
    db.session.delete(attachment)
    db.session.commit()
