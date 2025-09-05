from sqlalchemy import (Boolean, Column, DateTime, ForeignKey, Index, Integer,
                        String, Table, Text, UniqueConstraint, func)
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.orm import backref, relationship

from . import db

# tags association (plain table)
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


# association object (class) for TestCase <-> TestSuite with position
class TestCaseSuite(db.Model):
    __tablename__ = "test_case_suites"

    test_case_id = Column(
        Integer, ForeignKey("test_cases.id", ondelete="CASCADE"), primary_key=True
    )
    suite_id = Column(
        Integer, ForeignKey("test_suites.id", ondelete="CASCADE"), primary_key=True
    )
    position = Column(Integer, nullable=True)

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


class TestCase(db.Model):
    __tablename__ = "test_cases"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    preconditions = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
    expected_result = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    is_deleted = Column(Boolean, default=False, nullable=False)

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

    __table_args__ = (
        UniqueConstraint("name", "is_deleted", name="uq_testcase_name_active"),
        Index("ix_test_cases_is_deleted", "is_deleted"),
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

    test_case = relationship("TestCase", back_populates="steps", passive_deletes=True)

    __table_args__ = (
        UniqueConstraint("test_case_id", "position", name="uq_steps_per_case_position"),
        Index("ix_steps_test_case_id", "test_case_id"),
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

    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    is_deleted = Column(Boolean, default=False, nullable=False)

    # `case_links` is provided automatically by backref in TestCaseSuite
    test_cases = association_proxy("case_links", "test_case")

    def __repr__(self):
        return f"<TestSuite {self.id} {self.name}>"


class Tag(db.Model):
    __tablename__ = "tags"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True)
    test_cases = relationship(
        "TestCase",
        secondary=test_case_tags,
        back_populates="tags",
        passive_deletes=True,
    )

    def __repr__(self):
        return f"<Tag {self.name}>"
