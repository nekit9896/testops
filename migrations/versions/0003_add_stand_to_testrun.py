"""add stand column to testrun_results

Revision ID: 0003_add_stand_to_testrun_results
Revises: 0002_create_attachments_table
Create Date: 2025-11-14 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0003_add_stand_to_testrun"
down_revision = "0002_create_attachments_table"
branch_labels = None
depends_on = None


def upgrade():
    # Добавляем nullable колонку stand и индекс для поиска
    op.add_column(
        "testrun_results", sa.Column("stand", sa.String(length=128), nullable=True)
    )
    op.create_index(
        op.f("ix_testrun_results_stand"), "testrun_results", ["stand"], unique=False
    )


def downgrade():
    # Откат — удалить индекс и колонку
    op.drop_index(op.f("ix_testrun_results_stand"), table_name="testrun_results")
    op.drop_column("testrun_results", "stand")
