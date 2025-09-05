"""initial empty revision

Revision ID: 0001_create_test_cases_models
Revises:
Create Date: 2025-09-05 00:00:00.000000

"""

import sqlalchemy as sa  # noqa: F401
from alembic import op  # noqa: F401

# revision identifiers, used by Alembic.
revision = "0001_create_test_cases_models"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Database already contains the schema (created earlier).
    # This is an empty "stamp" migration so Alembic has a head.
    pass


def downgrade():
    pass
