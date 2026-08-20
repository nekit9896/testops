"""CLI-обёртка: python -m scripts.validate_postgres_tables (из корня /app)."""

from helpers.postgres_schema import main

if __name__ == "__main__":
    main()
