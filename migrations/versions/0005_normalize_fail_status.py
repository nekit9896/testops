"""normalize legacy run status fail to failed

Revision ID: 0005_normalize_fail_status
Revises: 0004_add_status_counts_to_testrun
Create Date: 2026-08-05 00:00:00.000000
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "0005_normalize_fail_status"
down_revision = "0004_add_status_counts_to_testrun"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("UPDATE testrun_results SET status = 'failed' WHERE status = 'fail'")


def downgrade():
    op.execute("UPDATE testrun_results SET status = 'fail' WHERE status = 'failed'")
