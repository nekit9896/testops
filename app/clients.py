# Инициализация Minio client
import os

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

    def put_object(
        self,
        bucket_name,
        object_name,
        file_stream,
        content_length=None,
        content_type=None,
        **kwargs
    ):
        """
        Backwards-compatible wrapper.
        Поддерживает:
          - positional calls: put_object(b, obj, stream, length)
          - keyword: content_length=...
          - alias length=... (если кто-то передал length)
          - optional content_type
        """
        try:
            # backward compatibility: accept legacy 'length' kw
            if "length" in kwargs and content_length is None:
                content_length = kwargs.get("length")
            # if still None, pass -1 (minio accepts unknown length as -1 for some versions)
            length_to_pass = content_length if content_length is not None else -1
            # call underlying SDK
            # ensure file_stream is at correct position is caller responsibility
            self.minio_client.put_object(
                bucket_name,
                object_name,
                file_stream,
                length=length_to_pass,
                content_type=content_type,
            )
        except Exception:
            logger.exception(
                "put_object failed", bucket=bucket_name, object=object_name
            )
            raise

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
