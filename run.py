from flask_migrate import Migrate

from app import create_app, db
from constants import HOST, PORT

app = create_app()
# Инициализация миграций
migrate = Migrate(app, db)

if __name__ == "__main__":
    app.run(host=HOST, port=PORT)
