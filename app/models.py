from sqlalchemy import (Boolean, Column, DateTime, ForeignKey, Integer, String,
                        Table, Text, UniqueConstraint, func)
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.orm import backref, relationship

from . import db

# Ассоциация тегов для многих ко многим
test_case_tags = Table(
    "test_case_tags",
    db.Model.metadata,
    Column(
        "test_case_id",
        Integer,
        ForeignKey("test_cases.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "tag_id", Integer, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True
    ),
)


# TestResults model
class TestResult(db.Model):
    __tablename__ = "testrun_results"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    run_name = db.Column(db.String(255), nullable=False)
    start_date = db.Column(db.DateTime, nullable=True)
    end_date = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(50), nullable=False)
    created_at = db.Column(db.DateTime, default=func.now(), nullable=False)
    is_deleted = db.Column(db.Boolean, default=False)

    def __repr__(self):
        return f"<TestRun {self.run_name} ({self.created_at})>"


# Таблица ассоциаций TestCase <-> TestSuite для реализации многих ко многим
class TestCaseSuite(db.Model):
    __tablename__ = "test_case_suites"

    test_case_id = Column(
        Integer, ForeignKey("test_cases.id", ondelete="CASCADE"), primary_key=True
    )
    suite_id = Column(
        Integer, ForeignKey("test_suites.id", ondelete="CASCADE"), primary_key=True
    )
    position = Column(Integer, nullable=True)

    # ORM связи к основным сущностям (link -> test_case, link -> suite)
    test_case = relationship(
        "TestCase", back_populates="suite_links", passive_deletes=True
    )
    suite = relationship("TestSuite", back_populates="case_links", passive_deletes=True)

    def __repr__(self):
        return f"<TestCaseSuite tc={self.test_case_id} suite={self.suite_id} pos={self.position}>"


class TestCase(db.Model):
    __tablename__ = "test_cases"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    preconditions = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
    expected_result = Column(Text, nullable=True)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )
    deleted_at = Column(DateTime, nullable=True)
    is_deleted = Column(Boolean, default=False, nullable=False)

    steps = relationship(
        "TestCaseStep",
        back_populates="test_case",
        order_by="TestCaseStep.position",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    # Ассоциативные объектные зависимости (используем link-объекты)
    suite_links = relationship(
        "TestCaseSuite",
        back_populates="test_case",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    suites = association_proxy("suite_links", "suite")

    # Тэги (plain M:N table) — passive_deletes=True оптимизирует удаление при ON DELETE CASCADE
    tags = relationship(
        "Tag",
        secondary=test_case_tags,
        back_populates="test_cases",
        passive_deletes=True,
    )

    __table_args__ = (
        UniqueConstraint("name", "is_deleted", name="uq_testcase_name_active"),
    )

    def __repr__(self):
        return f"<TestCase {self.id} {self.name}>"


class TestCaseStep(db.Model):
    __tablename__ = "test_case_steps"
    id = Column(Integer, primary_key=True, autoincrement=True)
    test_case_id = Column(
        Integer, ForeignKey("test_cases.id", ondelete="CASCADE"), nullable=False
    )
    position = Column(Integer, nullable=False)
    action = Column(Text, nullable=False)
    expected = Column(Text, nullable=True)
    attachments = Column(Text, nullable=True)

    test_case = relationship("TestCase", back_populates="steps")

    __table_args__ = (
        UniqueConstraint("test_case_id", "position", name="uq_steps_per_case_position"),
    )

    def __repr__(self):
        return f"<Step #{self.position} of TestCase {self.test_case_id}>"


class TestSuite(db.Model):
    __tablename__ = "test_suites"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    parent_id = Column(
        Integer, ForeignKey("test_suites.id", ondelete="SET NULL"), nullable=True
    )

    children = relationship(
        "TestSuite",
        backref=backref("parent", remote_side=[id]),
        cascade="all, delete-orphan",
    )

    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )
    is_deleted = Column(Boolean, default=False, nullable=False)

    ase_links = relationship(
        "TestCaseSuite",
        back_populates="suite",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    test_cases = association_proxy("case_links", "test_case")

    def __repr__(self):
        return f"<TestSuite {self.id} {self.name}>"


class Tag(db.Model):
    __tablename__ = "tags"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True)
    test_cases = relationship(
        "TestCase", secondary=test_case_tags, back_populates="tags"
    )

    def __repr__(self):
        return f"<Tag {self.name}>"
