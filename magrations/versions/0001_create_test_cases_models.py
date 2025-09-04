import sqlalchemy as sa
from alembic import op

# Идентификатор ревизии, используется Alembic.
revision = "0001_create_test_cases_models"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # --- test_suites ---
    op.create_table(
        "test_suites",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "is_deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
    )
    # Добавить внешний ключ для родительской
    op.create_foreign_key(
        "fk_test_suites_parent",
        source_table="test_suites",
        referent_table="test_suites",
        local_cols=["parent_id"],
        remote_cols=["id"],
        ondelete="SET NULL",
    )

    # --- test_cases ---
    op.create_table(
        "test_cases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("preconditions", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("expected_result", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column(
            "is_deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
    )

    # Ограничение уникальности: разрешить то же имя, если удаленный флаг отличается
    op.create_unique_constraint(
        "uq_testcase_name_active", "test_cases", ["name", "is_deleted"]
    )

    # --- test_case_steps ---
    op.create_table(
        "test_case_steps",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("test_case_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("expected", sa.Text(), nullable=True),
        sa.Column("attachments", sa.Text(), nullable=True),
    )
    op.create_foreign_key(
        "fk_steps_test_case",
        source_table="test_case_steps",
        referent_table="test_cases",
        local_cols=["test_case_id"],
        remote_cols=["id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        "uq_steps_per_case_position", "test_case_steps", ["test_case_id", "position"]
    )

    # --- test_case_suites ---
    op.create_table(
        "test_case_suites",
        sa.Column("test_case_id", sa.Integer(), nullable=False),
        sa.Column("suite_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("test_case_id", "suite_id", name="pk_test_case_suites"),
    )
    op.create_foreign_key(
        "fk_tcs_test_case",
        source_table="test_case_suites",
        referent_table="test_cases",
        local_cols=["test_case_id"],
        remote_cols=["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_tcs_suite",
        source_table="test_case_suites",
        referent_table="test_suites",
        local_cols=["suite_id"],
        remote_cols=["id"],
        ondelete="CASCADE",
    )

    # --- tags and association ---
    op.create_table(
        "tags",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=100), nullable=False, unique=True),
    )
    op.create_table(
        "test_case_tags",
        sa.Column("test_case_id", sa.Integer(), nullable=False),
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("test_case_id", "tag_id", name="pk_test_case_tags"),
    )
    op.create_foreign_key(
        "fk_tct_test_case",
        source_table="test_case_tags",
        referent_table="test_cases",
        local_cols=["test_case_id"],
        remote_cols=["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_tct_tag",
        source_table="test_case_tags",
        referent_table="tags",
        local_cols=["tag_id"],
        remote_cols=["id"],
        ondelete="CASCADE",
    )

    # Optional indexes: ускорим частые фильтры
    op.create_index("ix_test_cases_is_deleted", "test_cases", ["is_deleted"])
    op.create_index("ix_test_suites_is_deleted", "test_suites", ["is_deleted"])
    op.create_index("ix_steps_test_case_id", "test_case_steps", ["test_case_id"])


def downgrade():
    op.drop_index("ix_steps_test_case_id", table_name="test_case_steps")
    op.drop_index("ix_test_suites_is_deleted", table_name="test_suites")
    op.drop_index("ix_test_cases_is_deleted", table_name="test_cases")

    op.drop_table("test_case_tags")
    op.drop_table("tags")
    op.drop_table("test_case_suites")
    op.drop_table("test_case_steps")
    op.drop_table("test_cases")
    op.drop_table("test_suites")
