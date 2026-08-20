"""create full testops schema if tables are missing

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-08-19 00:00:00.000000

Идемпотентная baseline-миграция: на пустой БД создаёт все таблицы,
на уже существующей схеме ничего не ломает.

downgrade удаляет только таблицы, которые upgrade реально создал.
Таблицы, которые уже были в БД до этой ревизии, не трогает.
"""

from typing import Set

import sqlalchemy as sa
from alembic import op

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None

# Служебная таблица: какие объекты создал именно этот upgrade.
CREATED_TABLES_META = "_0001_created_tables"

DROP_ORDER = (
    "attachments",
    "test_case_tags",
    "test_case_suites",
    "test_case_steps",
    "testrun_results",
    "test_suites",
    "tags",
    "test_cases",
)


def _table_names() -> Set[str]:
    """Возвращает имена таблиц в текущей схеме public."""
    return set(sa.inspect(op.get_bind()).get_table_names())


def _remember_created(created: list[str]) -> None:
    """Сохраняет список таблиц, созданных этим upgrade, для безопасного downgrade."""
    if not created:
        return
    op.create_table(
        CREATED_TABLES_META,
        sa.Column("table_name", sa.String(64), primary_key=True),
    )
    created_table = sa.table(
        CREATED_TABLES_META,
        sa.column("table_name", sa.String),
    )
    op.bulk_insert(
        created_table,
        [{"table_name": name} for name in created],
    )


def upgrade() -> None:
    """Создаёт отсутствующие таблицы схемы TestOps и запоминает, какие именно созданы."""
    existing = _table_names()
    created: list[str] = []

    if "test_cases" not in existing:
        op.create_table(
            "test_cases",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("preconditions", sa.Text(), nullable=True),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("expected_result", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "is_deleted",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
            sa.UniqueConstraint("name", "is_deleted", name="uq_testcase_name_active"),
        )
        op.create_index("ix_test_cases_is_deleted", "test_cases", ["is_deleted"])
        created.append("test_cases")

    if "tags" not in existing:
        op.create_table(
            "tags",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("name", sa.String(100), nullable=False, unique=True),
            sa.Column(
                "is_deleted",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )
        op.create_index("ix_tags_is_deleted", "tags", ["is_deleted"])
        created.append("tags")

    if "test_suites" not in existing:
        op.create_table(
            "test_suites",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column(
                "parent_id",
                sa.Integer(),
                sa.ForeignKey("test_suites.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column(
                "is_deleted",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )
        created.append("test_suites")

    if "test_case_steps" not in existing:
        op.create_table(
            "test_case_steps",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "test_case_id",
                sa.Integer(),
                sa.ForeignKey("test_cases.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("position", sa.Integer(), nullable=False),
            sa.Column("action", sa.Text(), nullable=False),
            sa.Column("expected", sa.Text(), nullable=True),
            sa.Column("attachments", sa.Text(), nullable=True),
            sa.UniqueConstraint(
                "test_case_id", "position", name="uq_steps_per_case_position"
            ),
        )
        op.create_index("ix_steps_test_case_id", "test_case_steps", ["test_case_id"])
        created.append("test_case_steps")

    if "test_case_suites" not in existing:
        op.create_table(
            "test_case_suites",
            sa.Column(
                "test_case_id",
                sa.Integer(),
                sa.ForeignKey("test_cases.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column(
                "suite_id",
                sa.Integer(),
                sa.ForeignKey("test_suites.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column("position", sa.Integer(), nullable=True),
        )
        created.append("test_case_suites")

    if "test_case_tags" not in existing:
        op.create_table(
            "test_case_tags",
            sa.Column(
                "test_case_id",
                sa.Integer(),
                sa.ForeignKey("test_cases.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column(
                "tag_id",
                sa.Integer(),
                sa.ForeignKey("tags.id", ondelete="CASCADE"),
                primary_key=True,
            ),
        )
        created.append("test_case_tags")

    if "attachments" not in existing:
        op.create_table(
            "attachments",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "test_case_id",
                sa.Integer(),
                sa.ForeignKey("test_cases.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("original_filename", sa.String(1024), nullable=False),
            sa.Column("object_name", sa.String(2048), nullable=False, unique=True),
            sa.Column("bucket", sa.String(255), nullable=False),
            sa.Column("content_type", sa.String(255), nullable=True),
            sa.Column("size", sa.BigInteger(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
        )
        op.create_index("ix_attachments_test_case_id", "attachments", ["test_case_id"])
        created.append("attachments")

    if "testrun_results" not in existing:
        op.create_table(
            "testrun_results",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("run_name", sa.String(255), nullable=False),
            sa.Column("start_date", sa.DateTime(), nullable=True),
            sa.Column("end_date", sa.DateTime(), nullable=True),
            sa.Column("stand", sa.String(128), nullable=True),
            sa.Column("status", sa.String(50), nullable=False),
            sa.Column("passed_count", sa.Integer(), nullable=True),
            sa.Column("failed_count", sa.Integer(), nullable=True),
            sa.Column("broken_count", sa.Integer(), nullable=True),
            sa.Column("skipped_count", sa.Integer(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column("is_deleted", sa.Boolean(), server_default=sa.false()),
        )
        op.create_index("ix_testrun_results_stand", "testrun_results", ["stand"])
        created.append("testrun_results")

    _remember_created(created)


def downgrade() -> None:
    """Удаляет только таблицы, созданные upgrade этой ревизии.

    Если все таблицы уже были до миграции, служебной метки нет - ничего не дропаем.
    """
    existing = _table_names()
    if CREATED_TABLES_META not in existing:
        return

    bind = op.get_bind()
    created = {
        row[0]
        for row in bind.execute(sa.text(f"SELECT table_name FROM {CREATED_TABLES_META}"))
    }
    for name in DROP_ORDER:
        if name in created and name in existing:
            op.drop_table(name)
    op.drop_table(CREATED_TABLES_META)
