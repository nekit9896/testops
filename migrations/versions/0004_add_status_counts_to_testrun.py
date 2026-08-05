"""add status count columns to testrun_results

Revision ID: 0004_add_status_counts_to_testrun
Revises: 0003_add_stand_to_testrun
Create Date: 2026-08-05 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0004_add_status_counts_to_testrun"
down_revision = "0003_add_stand_to_testrun"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "testrun_results",
        sa.Column("passed_count", sa.Integer(), nullable=True),
    )
    op.add_column(
        "testrun_results",
        sa.Column("failed_count", sa.Integer(), nullable=True),
    )
    op.add_column(
        "testrun_results",
        sa.Column("broken_count", sa.Integer(), nullable=True),
    )
    op.add_column(
        "testrun_results",
        sa.Column("skipped_count", sa.Integer(), nullable=True),
    )


def downgrade():
    op.drop_column("testrun_results", "skipped_count")
    op.drop_column("testrun_results", "broken_count")
    op.drop_column("testrun_results", "failed_count")
    op.drop_column("testrun_results", "passed_count")
