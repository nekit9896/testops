import os


class Config:
    DEBUG = True
    FLASK_ENV = "development"
    SECRET_KEY = ""
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL", "postgresql://testops:@db:5432/testops"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
