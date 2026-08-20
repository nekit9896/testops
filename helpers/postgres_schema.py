"""Проверка наличия обязательных таблиц PostgreSQL для TestOps."""

from __future__ import annotations

import sys
from typing import Set

from sqlalchemy import inspect, text

from app import create_app, db

REQUIRED_TABLES = (
    "attachments",
    "tags",
    "test_case_steps",
    "test_case_suites",
    "test_case_tags",
    "test_cases",
    "test_suites",
    "testrun_results",
)


def _existing_tables() -> Set[str]:
    """Возвращает имена таблиц в текущей БД приложения."""
    inspector = inspect(db.engine)
    return set(inspector.get_table_names())


def validate_postgres_tables() -> None:
    """Завершает процесс с кодом 1, если нет соединения или не хватает таблиц."""
    app = create_app()
    with app.app_context():
        with db.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        existing = _existing_tables()
        missing = [name for name in REQUIRED_TABLES if name not in existing]
        if missing:
            print("PostgreSQL schema is incomplete, missing tables:")
            for name in missing:
                print(f"  - {name}")
            print("Run once: flask db upgrade")
            sys.exit(1)
        print("PostgreSQL schema OK: all required tables are present")


def main() -> None:
    """Точка входа CLI."""
    validate_postgres_tables()
