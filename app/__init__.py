from flask import Flask
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy

from logger import init_logger

from .config import Config

db = SQLAlchemy()
# Инициализация миграций
migrate = Migrate()


def create_app():
    """
    Создает и конфигурирует экземпляр приложения Flask
    Детали:
    Используется название текущего модуля как имя приложения
    Конфигурация загружается из объекта Config
    db.init_app(app) - вызывается для настройки приложения на работу с бд
    migrate.init_app(app, db) - для настройки миграций бд
    Импорт внешних методов, чтобы не зацикливались;
    Маршруты регистрируются через Blueprint
    :return: возвращает сконфигурированный объект Flask приложения
    """
    # При инициализации указываете папки с html и css в корне проекта
    app = Flask(__name__, template_folder="../templates", static_folder="../static")
    app.config.from_object(Config)
    # Инициализирует логер
    logger = init_logger()

    @app.before_request
    def log_request_info() -> None:
        """
        Логирует каждый запрос
        """
        logger.info("Выполнение запроса")

    # Инициализация баз данных
    db.init_app(app)
    migrate.init_app(app, db)

    # Регистрация маршрутов
    from .errors import errors_bp
    from .routes import bp as routes_bp

    app.register_blueprint(routes_bp)
    app.register_blueprint(errors_bp)

    return app
