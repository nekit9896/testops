# Инициализация Minio client
import os
import tempfile
from typing import Any, Optional

from minio import Minio, S3Error

from logger import init_logger

logger = init_logger()


# Инициализация MinIO client
class MinioClient:
    def __init__(self):
        """
        Ожидается только хост с портом, без "http://".
        """
        self.minio_endpoint = os.getenv("MINIO_ENDPOINT", "minio:9000")

        self.minio_client = Minio(
            endpoint=self.minio_endpoint,  # Без протокола
            access_key=os.getenv("MINIO_ACCESS_KEY", "minioadmin"),
            secret_key=os.getenv("MINIO_SECRET_KEY", "minioadmin"),
            secure=False,  # True, если используется HTTPS
        )

    def ensure_bucket_exists(self, bucket_name):
        """
        Создает бакет, если его нет.
        """
        try:
            if not self.minio_client.bucket_exists(bucket_name):
                self.minio_client.make_bucket(bucket_name)
                logger.info("Бакет успешно создан.", bucket_name=bucket_name)
            else:
                pass
        except S3Error:
            logger.exception("Ошибка при создании бакета")

    def put_object(self, *args: Any, **kwargs: Any) -> None:
        """
        Поддерживает:
          - put_object(bucket, object_name, file_stream, length)
          - put_object(bucket_name=b..., object_name=b..., file_stream=..., content_length=...)
          - alias 'length' в kwargs
          - optional content_type

        Поведение:
          - если content_length (или length) задан и > 0 -> используем его
          - если не задан, но file_stream.seekable() -> вычисляем размер через seek/tell
          - если не задан и не seekable -> пишем поток во временный файл и загружаем из него
          - в любом случае перед загрузкой стараемся выполнить file_stream.seek(0)
          - content_type передаём в MinIO только если он не None
        """
        # Разбор аргументов (поддерживаем positional вызов)
        bucket_name: Optional[str] = None
        object_name: Optional[str] = None
        file_stream = None
        content_length: Optional[int] = None

        # Позиционные параметры
        if len(args) >= 1:
            bucket_name = args[0]
        if len(args) >= 2:
            object_name = args[1]
        if len(args) >= 3:
            file_stream = args[2]
        if len(args) >= 4 and content_length is None:
            # 4-й позиционный аргумент — legacy length
            content_length = args[3]

        # Переопределение kwargs / обработка алиасов
        bucket_name = kwargs.get("bucket_name", bucket_name)
        object_name = kwargs.get("object_name", object_name) or kwargs.get("file_path", object_name)
        file_stream = kwargs.get("file_stream", file_stream) or kwargs.get("data", file_stream)
        # content_length может быть в kwargs под разными именами
        if content_length is None:
            content_length = kwargs.get("content_length", kwargs.get("length"))

        content_type = kwargs.get("content_type", None)

        if not bucket_name or not object_name or file_stream is None:
            raise ValueError("put_object: обязательные параметры (bucket_name, object_name, file_stream) не обнаружены")

        tmp_file_path: Optional[str] = None
        used_stream = file_stream
        restored_position = None

        try:
            # Попытка использовать переданный content_length если он валиден (>0)
            if content_length is not None:
                try:
                    content_length = int(content_length)
                    if content_length <= 0:
                        content_length = None
                except Exception:
                    content_length = None

            # Если длина неизвестна — попробуем вычислить, если поток seekable
            if content_length is None:
                try:
                    if hasattr(file_stream, "seek") and hasattr(file_stream, "tell"):
                        # Сохраняем текущую позицию (если возможно)
                        try:
                            restored_position = file_stream.tell()
                        except Exception:
                            restored_position = None

                        # вычисляем полный размер
                        try:
                            file_stream.seek(0, os.SEEK_END)
                            end_pos = file_stream.tell()
                            # если удалось, размер = end_pos (если предыдущая позиция не нулевая, это абсолютная позиция)
                            content_length = int(end_pos)
                            # вернёмся к началу для загрузки
                            try:
                                file_stream.seek(0)
                            except Exception:
                                # если не получилось - будем делать fallback во временный файл
                                content_length = None
                        finally:
                            # если вычисление не дало size (==0) — сбрасываем
                            if content_length == 0:
                                content_length = None
                except Exception:
                    content_length = None

            # Если всё ещё нет размера — fallback: пишем поток во временный файл и используем его
            if content_length is None:
                # создаём tmp файл и копируем туда поток
                tmp_fd, tmp_file_path = tempfile.mkstemp(prefix="minio_put_", suffix=".tmp")
                os.close(tmp_fd)
                total = 0
                try:
                    # попробуем вернуться в начало, если поток поддерживает
                    try:
                        file_stream.seek(0)
                    except Exception:
                        pass

                    with open(tmp_file_path, "wb") as wf:
                        while True:
                            chunk = file_stream.read(64 * 1024)
                            if not chunk:
                                break
                            if isinstance(chunk, str):
                                # safety: если кто-то передал текстовый stream
                                chunk = chunk.encode()
                            wf.write(chunk)
                            total += len(chunk)
                    content_length = total
                except Exception:
                    # при ошибке попробуем удалить tmp и пробросить
                    if tmp_file_path and os.path.exists(tmp_file_path):
                        try:
                            os.unlink(tmp_file_path)
                        except Exception:
                            logger.exception("put_object: не удалось удалить tmp после ошибки", tmp_path=tmp_file_path)
                    raise

                # откроем tmp для чтения в бинарном режиме и используем его как stream
                used_stream = open(tmp_file_path, "rb")

            # Перед загрузкой убедимся, что stream в начале
            try:
                used_stream.seek(0)
            except Exception:
                # если не получается промотать — логируем, но попытаемся загрузить
                logger.debug("put_object: не удалось найти начало потока, продолжаем",
                             bucket_name=bucket_name, object_name=object_name)

            # Подготовим kwargs для minio SDK — content_type добавляем только если есть
            put_kwargs = {"length": content_length}
            if content_type is not None:
                put_kwargs["content_type"] = content_type

            # Наконец, вызов SDK
            self.minio_client.put_object(bucket_name, object_name, used_stream, **put_kwargs)
            logger.info("put_object: uploaded", bucket=bucket_name, object=object_name, length=content_length)

        except Exception:
            logger.exception("put_object failed", bucket=bucket_name, object=object_name)
            raise

        finally:
            # Закрываем tmp, если мы её открывали (но не закрываем исходный stream)
            try:
                if tmp_file_path and used_stream and not used_stream.closed:
                    used_stream.close()
            except Exception:
                logger.debug("put_object: не удалось закрыть временный поток", tmp_path=tmp_file_path)

            # если создали tmp — удалим его
            if tmp_file_path:
                try:
                    os.unlink(tmp_file_path)
                except Exception:
                    logger.exception("put_object: не удалось удалить файл tmp", tmp_path=tmp_file_path)

            # Восстановим позицию исходного потока, если возможно и если у нас бывает смысл
            try:
                if restored_position is not None:
                    try:
                        file_stream.seek(restored_position)
                    except Exception:
                        logger.debug("put_object: не удалось восстановить исходную позицию потока")
            except Exception:
                logger.debug("put_object: логика восстановления исходной позиции не удалась")

    def list_objects(self, bucket_name, prefix):
        """Возвращает объекты, подходящие под префикс."""
        return self.minio_client.list_objects(
            bucket_name, prefix=prefix, recursive=True
        )

    def download_file(self, bucket_name, object_name, local_path):
        """
        Скачивает объект потоково на local_path
        """
        try:
            response = self.minio_client.get_object(bucket_name, object_name)
            with open(local_path, "wb") as f:
                for data in response.stream(32 * 1024):
                    f.write(data)
            try:
                response.close()
            except Exception:
                pass
        except Exception:
            logger.exception(
                "download_file failed",
                bucket=bucket_name,
                object=object_name,
                local_path=local_path,
            )
            raise

    def stat_object(self, bucket_name: str, object_name: str):
        """Возвращает metadata объекта (stat_object) — для проверки существования и размера."""
        try:
            return self.minio_client.stat_object(bucket_name, object_name)
        except S3Error:
            logger.exception(
                "stat_object failed", bucket=bucket_name, object_name=object_name
            )
            raise

    def get_object_stream(self, bucket_name: str, object_name: str):
        """Возвращает объект-ответ от minio.get_object(...)"""
        try:
            return self.minio_client.get_object(bucket_name, object_name)
        except S3Error:
            logger.exception(
                "get_object_stream failed", bucket=bucket_name, object_name=object_name
            )
            raise

    def remove_object(self, bucket_name: str, object_name: str):
        """Удаление объекта из бакета (thin wrapper)"""
        try:
            self.minio_client.remove_object(bucket_name, object_name)
        except S3Error:
            logger.exception(
                "remove_object failed", bucket=bucket_name, object_name=object_name
            )
            raise
