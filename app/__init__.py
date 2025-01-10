from flask import Flask
from .config import Config

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Регистрация маршрутов
    from .routes import bp as routes_bp
    app.register_blueprint(routes_bp)