# Инициализация Minio client
import logging
import os

from minio import Minio, S3Error

logging.basicConfig(level=logging.DEBUG)


class MinioClient:
    def __init__(self):
        # Ожидается только хост с портом, без "http://".
        self.minio_endpoint = os.getenv("MINIO_ENDPOINT", "minio:9000")

        self.minio_client = Minio(
            endpoint=self.minio_endpoint,  # Без протокола
            access_key=os.getenv("MINIO_ACCESS_KEY", "minioadmin"),
            secret_key=os.getenv("MINIO_SECRET_KEY", "minioadmin"),
            secure=False,  # True, если используется HTTPS
        )

    def ensure_bucket_exists(self, bucket_name):
        """Создает бакет, если его нет."""
        try:
            if not self.minio_client.bucket_exists(bucket_name):
                self.minio_client.make_bucket(bucket_name)
                print(f"Bucket '{bucket_name}' успешно создан.")
            else:
                print(f"Bucket '{bucket_name}' уже существует.")
        except S3Error as e:
            print(f"Ошибка при создании бакета: {e}")

    def put_object(self, bucket_name, file_path, file_stream, content_length):
        self.minio_client.put_object(
            bucket_name, file_path, file_stream, length=content_length
        )
