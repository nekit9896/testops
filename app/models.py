from datetime import datetime

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class TestRun(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    run_name = db.Column(db.String(128), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now())
    result_folder = db.Column(db.String(256), nullable=False)

    def __repr__(self):
        return f"<TestRun {self.run_name} ({self.created_at})>"
