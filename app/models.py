import uuid
from pathlib import Path

import sqlalchemy as sqlalchemy
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.orm import backref, relationship
from werkzeug.utils import secure_filename

from . import db

# tags association (plain table)
test_case_tags = sqlalchemy.Table(
    "test_case_tags",
    db.Model.metadata,
    sqlalchemy.Column(
        "test_case_id",
        sqlalchemy.Integer,
        sqlalchemy.ForeignKey("test_cases.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    sqlalchemy.Column(
        "tag_id",
        sqlalchemy.Integer,
        sqlalchemy.ForeignKey("tags.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


# TestResults model
class TestResult(db.Model):
    __tablename__ = "testrun_results"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    run_name = db.Column(db.String(255), nullable=False)
    start_date = db.Column(db.DateTime, nullable=True)
    end_date = db.Column(db.DateTime, nullable=True)
    stand = db.Column(db.String(128), nullable=True, index=True)
    status = db.Column(db.String(50), nullable=False)
    created_at = db.Column(db.DateTime, default=sqlalchemy.func.now(), nullable=False)
    is_deleted = db.Column(db.Boolean, default=False)

    def __repr__(self):
        return f"<TestRun {self.run_name} ({self.created_at})>"


# association object (class) for TestCase <-> TestSuite with position
class TestCaseSuite(db.Model):
    __tablename__ = "test_case_suites"

    test_case_id = sqlalchemy.Column(
        sqlalchemy.Integer,
        sqlalchemy.ForeignKey("test_cases.id", ondelete="CASCADE"),
        primary_key=True,
    )
    suite_id = sqlalchemy.Column(
        sqlalchemy.Integer,
        sqlalchemy.ForeignKey("test_suites.id", ondelete="CASCADE"),
        primary_key=True,
    )
    position = sqlalchemy.Column(sqlalchemy.Integer, nullable=True)

    # use backref to avoid ordering issues:
    test_case = relationship(
        "TestCase",
        backref=backref(
            "suite_links", cascade="all, delete-orphan", passive_deletes=True
        ),
    )
    suite = relationship(
        "TestSuite",
        backref=backref(
            "case_links", cascade="all, delete-orphan", passive_deletes=True
        ),
    )

    def __repr__(self):
        return f"<TestCaseSuite tc={self.test_case_id} suite={self.suite_id} pos={self.position}>"


class Attachment(db.Model):
    __tablename__ = "attachments"

    id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True, autoincrement=True)
    test_case_id = sqlalchemy.Column(
        sqlalchemy.Integer,
        sqlalchemy.ForeignKey("test_cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    original_filename = sqlalchemy.Column(sqlalchemy.String(1024), nullable=False)
    object_name = sqlalchemy.Column(
        sqlalchemy.String(2048), nullable=False, unique=True
    )  # ключ в MinIO
    bucket = sqlalchemy.Column(sqlalchemy.String(255), nullable=False)
    content_type = sqlalchemy.Column(sqlalchemy.String(255), nullable=True)
    size = sqlalchemy.Column(sqlalchemy.BigInteger, nullable=True)
    created_at = sqlalchemy.Column(
        sqlalchemy.DateTime(timezone=True),
        server_default=sqlalchemy.func.now(),
        nullable=False,
    )

    test_case = relationship(
        "TestCase", back_populates="attachments", passive_deletes=True
    )

    def __repr__(self):
        return f"<Attachment {self.id} {self.original_filename}>"

    @staticmethod
    def make_object_name(test_case_id: int, filename: str) -> str:
        """
        Генерирует уникальное имя объекта для хранения в MinIO.
        Формат: testcases/<test_case_id>/<uuid4hex>_<secure_filename>
        """
        # secure_filename удаляет не-ASCII, поэтому для кириллицы и других юникод-имен
        # добавляем безопасный fallback с сохранением расширения
        safe = secure_filename(filename or "") or ""
        if not safe or safe in {".", ".."}:
            ext = Path(filename or "").suffix
            base = "file"
            safe = f"{base}{ext}" if ext else base
        return f"testcases/{test_case_id}/{uuid.uuid4().hex}_{safe}"


class TestCase(db.Model):
    __tablename__ = "test_cases"
    id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True, autoincrement=True)
    name = sqlalchemy.Column(sqlalchemy.String(255), nullable=False)
    preconditions = sqlalchemy.Column(sqlalchemy.Text, nullable=True)
    description = sqlalchemy.Column(sqlalchemy.Text, nullable=True)
    expected_result = sqlalchemy.Column(sqlalchemy.Text, nullable=True)
    created_at = sqlalchemy.Column(
        sqlalchemy.DateTime(timezone=True),
        server_default=sqlalchemy.func.now(),
        nullable=False,
    )
    updated_at = sqlalchemy.Column(
        sqlalchemy.DateTime(timezone=True),
        server_default=sqlalchemy.func.now(),
        onupdate=sqlalchemy.func.now(),
        nullable=False,
    )
    deleted_at = sqlalchemy.Column(sqlalchemy.DateTime(timezone=True), nullable=True)
    is_deleted = sqlalchemy.Column(sqlalchemy.Boolean, default=False, nullable=False)

    # steps
    steps = relationship(
        "TestCaseStep",
        back_populates="test_case",
        order_by="TestCaseStep.position",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    # suites via association object: `suite_links` created by backref above
    # expose convenient proxy list:
    suites = association_proxy("suite_links", "suite")

    # tags
    tags = relationship(
        "Tag",
        secondary=test_case_tags,
        back_populates="test_cases",
        passive_deletes=True,
    )

    # attached files
    attachments = relationship(
        "Attachment",
        back_populates="test_case",
        order_by="Attachment.created_at",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        sqlalchemy.UniqueConstraint(
            "name", "is_deleted", name="uq_testcase_name_active"
        ),
        sqlalchemy.Index("ix_test_cases_is_deleted", "is_deleted"),
    )

    def __repr__(self):
        return f"<TestCase {self.id} {self.name}>"


class TestCaseStep(db.Model):
    __tablename__ = "test_case_steps"
    id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True, autoincrement=True)
    test_case_id = sqlalchemy.Column(
        sqlalchemy.Integer,
        sqlalchemy.ForeignKey("test_cases.id", ondelete="CASCADE"),
        nullable=False,
    )
    position = sqlalchemy.Column(sqlalchemy.Integer, nullable=False)
    action = sqlalchemy.Column(sqlalchemy.Text, nullable=False)
    expected = sqlalchemy.Column(sqlalchemy.Text, nullable=True)
    attachments = sqlalchemy.Column(sqlalchemy.Text, nullable=True)

    test_case = relationship("TestCase", back_populates="steps", passive_deletes=True)

    __table_args__ = (
        sqlalchemy.UniqueConstraint(
            "test_case_id", "position", name="uq_steps_per_case_position"
        ),
        sqlalchemy.Index("ix_steps_test_case_id", "test_case_id"),
    )

    def __repr__(self):
        return f"<Step #{self.position} of TestCase {self.test_case_id}>"


class TestSuite(db.Model):
    __tablename__ = "test_suites"
    id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True, autoincrement=True)
    name = sqlalchemy.Column(sqlalchemy.String(255), nullable=False)
    description = sqlalchemy.Column(sqlalchemy.Text, nullable=True)
    parent_id = sqlalchemy.Column(
        sqlalchemy.Integer,
        sqlalchemy.ForeignKey("test_suites.id", ondelete="SET NULL"),
        nullable=True,
    )

    children = relationship(
        "TestSuite",
        backref=backref("parent", remote_side=[id]),
        cascade="all, delete-orphan",
    )

    created_at = sqlalchemy.Column(
        sqlalchemy.DateTime(timezone=True),
        server_default=sqlalchemy.func.now(),
        nullable=False,
    )
    updated_at = sqlalchemy.Column(
        sqlalchemy.DateTime(timezone=True),
        server_default=sqlalchemy.func.now(),
        onupdate=sqlalchemy.func.now(),
        nullable=False,
    )
    is_deleted = sqlalchemy.Column(sqlalchemy.Boolean, default=False, nullable=False)

    # `case_links` is provided automatically by backref in TestCaseSuite
    test_cases = association_proxy("case_links", "test_case")

    def __repr__(self):
        return f"<TestSuite {self.id} {self.name}>"


class Tag(db.Model):
    __tablename__ = "tags"
    id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True, autoincrement=True)
    name = sqlalchemy.Column(sqlalchemy.String(100), nullable=False, unique=True)
    is_deleted = sqlalchemy.Column(sqlalchemy.Boolean, default=False, nullable=False)
    test_cases = relationship(
        "TestCase",
        secondary=test_case_tags,
        back_populates="tags",
        passive_deletes=True,
    )

    __table_args__ = (sqlalchemy.Index("ix_tags_is_deleted", "is_deleted"),)

    def __repr__(self):
        return f"<Tag {self.name}>"
