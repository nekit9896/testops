from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


# TestResults model
class TestResult(db.Model):
    __tablename__ = "testrun_results"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    run_name = db.Column(db.String(255), nullable=False)
    start_date = db.Column(db.DateTime, nullable=False)
    end_date = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(50), nullable=False)
    file_link = db.Column(db.String(255), nullable=False)
    is_deleted = db.Column(db.Boolean, default=False)

    def __repr__(self):
        return f"<TestRun {self.run_name} ({self.created_at})>"
