from flask import Flask
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy

from .config import Config

db = SQLAlchemy()
# Инициализация миграций
migrate = Migrate()


def create_app():
    """
    Создаем и конфигурируем экземпляр приложения Flask
    Детально:
    Используется название текущего модуля как имя приложения
    Загружается конфигурация из объекта Config
    db.init_app(app) — вызывается для настройки приложения на работу с БД
    migrate.init(app, db) — для настройки миграций БД
    Миграции внутри метода, чтобы не зацикливалось.
    Маршруты регистрируются через Blueprint
    :return: возвращает сконфигурированный объект Flask приложения
    """
    # При инициализации указываем папки с html и css в корне проекта
    app = Flask(__name__, template_folder="./templates", static_folder="./static")
    app.config.from_object(Config)

    # Инициализация базы данных
    db.init_app(app)
    migrate.init_app(app, db)

    # Регистрация маршрутов
    from .routes import bp as routes_bp

    app.register_blueprint(routes_bp)

    return app
