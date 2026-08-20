#!/bin/sh
#
# Старт flask-app: дождаться PostgreSQL и проверить, что таблицы схемы на месте.
#
# 1) Цикл до 30 попыток: SELECT 1 через SQLAlchemy.
#    Postgres после docker compose up поднимается не мгновенно; без ожидания
#    Flask падает на первом запросе к БД.
# 2) python -m scripts.validate_postgres_tables
#    Сверяет 8 обязательных таблиц. Если все на месте - upgrade не вызывается.
#    Если таблиц нет (новый стенд) - один раз flask db upgrade, затем проверка снова.
#    На сервере с уже живой схемой это no-op после первой успешной проверки.
# 3) exec flask run - подменяет shell процессом Flask, чтобы Docker слал
#    SIGTERM сразу приложению, а не оболочке.
#
set -eu

echo "Waiting for PostgreSQL..."
i=0
while [ "$i" -lt 30 ]; do
  if python -c "
from sqlalchemy import text
from app import create_app, db
app = create_app()
with app.app_context():
    with db.engine.connect() as conn:
        conn.execute(text('SELECT 1'))
"; then
    break
  fi
  i=$((i + 1))
  echo "Database is not ready yet ($i/30), retrying..."
  sleep 2
done

if [ "$i" -ge 30 ]; then
  echo "PostgreSQL did not become ready in time"
  exit 1
fi

echo "Validating PostgreSQL tables..."
if python -m scripts.validate_postgres_tables; then
  :
else
  echo "Schema incomplete, applying flask db upgrade once..."
  flask db upgrade
  python -m scripts.validate_postgres_tables
fi

echo "Starting Flask..."
exec flask run --host="${FLASK_RUN_HOST:-0.0.0.0}" --port="${FLASK_RUN_PORT:-5000}"
