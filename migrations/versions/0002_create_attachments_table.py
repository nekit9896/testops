"""create attachments

Revision ID: 0002_create_attachments_table
Revises: 0001_create_test_cases_models
Create Date: 2025-09-25 12:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0002_create_attachments_table"
down_revision = "0001_create_test_cases_models"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "attachments" not in inspector.get_table_names():
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


def downgrade() -> None:
    op.drop_index("ix_attachments_test_case_id", table_name="attachments")
    op.drop_table("attachments")
