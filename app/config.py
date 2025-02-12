import os

from minio import Minio


class Config:
    DEBUG = True
    FLASK_ENV = "development"
    SECRET_KEY = ""
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL", "postgresql://username:password@localhost/dbname"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
