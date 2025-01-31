from flask import Flask

from .config import Config
from .models import db


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Инициализация базы данных
    db.init_app(app)

    # Регистрация маршрутов
    from .routes import bp as routes_bp

    app.register_blueprint(routes_bp)

    return app
