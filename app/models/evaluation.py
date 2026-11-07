from ..extensions import db
from .common import utc_now


class Evaluation(db.Model):
    __tablename__ = "evaluations"
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("submissions.session_id", ondelete="RESTRICT"), nullable=False)
    case_version_id = db.Column(db.Integer, nullable=False)
    evaluation_no = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="PENDING")
    total_points_x2 = db.Column(db.Integer)
    input_hash = db.Column(db.String(64), nullable=False)
    config_json = db.Column(db.JSON, nullable=False, default=dict)
    feedback_json = db.Column(db.JSON, nullable=False, default=dict)
    created_at = db.Column(db.String(32), nullable=False, default=utc_now)
    __table_args__ = (
        db.ForeignKeyConstraint(["session_id", "case_version_id"], ["sessions.id", "sessions.case_version_id"], ondelete="RESTRICT"),
        db.UniqueConstraint("session_id", "evaluation_no"),
        db.UniqueConstraint("id", "session_id", "case_version_id"),
        db.UniqueConstraint("id", "session_id"),
        db.CheckConstraint("evaluation_no > 0", name="number_positive"),
        db.CheckConstraint("status IN ('PENDING','PROCESSING','VALID','NEEDS_REVIEW','ERROR')", name="status"),
        db.CheckConstraint("(status = 'VALID' AND total_points_x2 IS NOT NULL AND total_points_x2 BETWEEN 0 AND 200) OR (status != 'VALID' AND total_points_x2 IS NULL)", name="valid_total_only"),
        db.Index("ix_evaluations_session_status_number", "session_id", "status", "evaluation_no"),
    )


class EvaluationItem(db.Model):
    __tablename__ = "evaluation_items"
    id = db.Column(db.Integer, primary_key=True)
    evaluation_id = db.Column(db.Integer, nullable=False)
    criterion_id = db.Column(db.Integer, nullable=False)
    session_id = db.Column(db.Integer, nullable=False)
    case_version_id = db.Column(db.Integer, nullable=False)
    level = db.Column(db.String(20), nullable=False)
    points_x2 = db.Column(db.Integer)
    reason_text = db.Column(db.Text, nullable=False)
    __table_args__ = (
        db.ForeignKeyConstraint(["evaluation_id", "session_id", "case_version_id"], ["evaluations.id", "evaluations.session_id", "evaluations.case_version_id"], ondelete="RESTRICT"),
        db.ForeignKeyConstraint(["criterion_id", "case_version_id"], ["rubric_criteria.id", "rubric_criteria.case_version_id"], ondelete="RESTRICT"),
        db.UniqueConstraint("evaluation_id", "criterion_id"),
        db.UniqueConstraint("id", "session_id"),
        db.CheckConstraint("level IN ('ACHIEVED','PARTIAL','MISSED','UNDETERMINED')", name="level"),
        db.CheckConstraint("(level = 'UNDETERMINED' AND points_x2 IS NULL) OR (level != 'UNDETERMINED' AND points_x2 IS NOT NULL AND points_x2 BETWEEN 0 AND 200)", name="points"),
        db.CheckConstraint("level != 'MISSED' OR points_x2 = 0", name="missed_zero"),
    )


class Evidence(db.Model):
    __tablename__ = "evidence"
    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, nullable=False)
    session_id = db.Column(db.Integer, nullable=False)
    message_id = db.Column(db.Integer)
    event_id = db.Column(db.Integer)
    submission_session_id = db.Column(db.Integer, db.ForeignKey("submissions.session_id", ondelete="RESTRICT"))
    field_path = db.Column(db.String(100))
    quote_text = db.Column(db.Text, nullable=False)
    start_offset = db.Column(db.Integer)
    end_offset = db.Column(db.Integer)
    __table_args__ = (
        db.ForeignKeyConstraint(["item_id", "session_id"], ["evaluation_items.id", "evaluation_items.session_id"], ondelete="RESTRICT"),
        db.ForeignKeyConstraint(["message_id", "session_id"], ["messages.id", "messages.session_id"], ondelete="RESTRICT"),
        db.ForeignKeyConstraint(["event_id", "session_id"], ["session_events.id", "session_events.session_id"], ondelete="RESTRICT"),
        db.CheckConstraint("(message_id IS NOT NULL) + (event_id IS NOT NULL) + (submission_session_id IS NOT NULL) = 1", name="exactly_one_source"),
        db.CheckConstraint("submission_session_id IS NULL OR submission_session_id = session_id", name="submission_same_session"),
        db.CheckConstraint("(start_offset IS NULL AND end_offset IS NULL) OR (start_offset IS NOT NULL AND end_offset IS NOT NULL AND start_offset >= 0 AND end_offset > start_offset)", name="offset_range"),
    )
