"""add description column to testrun_results

Revision ID: 0002_add_description_to_testrun_results
Revises: 0001_initial_schema
Create Date: 2026-09-22 00:00:00.000000

Добавляет опциональную колонку description для прогонов (testrun_results).
DESCRIPTION — опциональный параметр, поэтому колонка nullable и без значения по умолчанию.
Миграция идемпотентна: не падает, если колонка уже существует.
"""

import sqlalchemy as sa
from alembic import op

revision = "0002_add_description_to_testrun_results"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def _existing_columns():
    inspector = sa.inspect(op.get_bind())
    return {col["name"] for col in inspector.get_columns("testrun_results")}


def upgrade() -> None:
    if "description" in _existing_columns():
        return
    op.add_column(
        "testrun_results",
        sa.Column("description", sa.String(512), nullable=True),
    )


def downgrade() -> None:
    if "description" not in _existing_columns():
        return
    op.drop_column("testrun_results", "description")
