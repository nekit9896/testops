"""add is_deleted to tags table

Revision ID: 0004_add_is_deleted_to_tags
Revises: 0003_add_stand_to_testrun
Create Date: 2025-12-11 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0004_add_is_deleted_to_tags"
down_revision = "0003_add_stand_to_testrun"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "tags",
        sa.Column(
            "is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.create_index("ix_tags_is_deleted", "tags", ["is_deleted"])


def downgrade():
    op.drop_index("ix_tags_is_deleted", table_name="tags")
    op.drop_column("tags", "is_deleted")
