from ..extensions import db
from .common import utc_now


class AIOperation(db.Model):
    __tablename__ = "ai_operations"
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("sessions.id", ondelete="RESTRICT"), nullable=False)
    evaluation_id = db.Column(db.Integer, unique=True)
    request_key = db.Column(db.String(100), nullable=False)
    input_hash = db.Column(db.String(64), nullable=False)
    kind = db.Column(db.String(16), nullable=False)
    status = db.Column(db.String(16), nullable=False, default="PENDING")
    expected_state_version = db.Column(db.Integer, nullable=False)
    input_payload_json = db.Column(db.JSON, nullable=False)
    started_at = db.Column(db.String(32), nullable=False, default=utc_now)
    finished_at = db.Column(db.String(32))
    __table_args__ = (
        db.ForeignKeyConstraint(["evaluation_id", "session_id"], ["evaluations.id", "evaluations.session_id"], ondelete="RESTRICT"),
        db.UniqueConstraint("session_id", "request_key"),
        db.UniqueConstraint("id", "session_id"),
        db.CheckConstraint("kind IN ('TURN','ACTION','ASSESSMENT')", name="kind"),
        db.CheckConstraint("status IN ('PENDING','RUNNING','SUCCEEDED','FAILED','CONFLICT')", name="status"),
        db.CheckConstraint("expected_state_version >= 0", name="state_version"),
        db.CheckConstraint("(kind = 'ASSESSMENT' AND evaluation_id IS NOT NULL) OR (kind != 'ASSESSMENT' AND evaluation_id IS NULL)", name="assessment_target"),
        db.Index("uq_ai_operations_one_running", "status", unique=True, sqlite_where=db.text("status = 'RUNNING'")),
    )


class AICall(db.Model):
    __tablename__ = "ai_calls"
    id = db.Column(db.Integer, primary_key=True)
    operation_id = db.Column(db.Integer, db.ForeignKey("ai_operations.id", ondelete="RESTRICT"), nullable=False)
    stage = db.Column(db.String(16), nullable=False)
    attempt_no = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(16), nullable=False, default="RESERVED")
    requested_at = db.Column(db.String(32), nullable=False, default=utc_now)
    reserved_cost_microusd = db.Column(db.Integer, nullable=False, default=0)
    actual_cost_microusd = db.Column(db.Integer)
    usage_json = db.Column(db.JSON, nullable=False, default=dict)
    configuration_json = db.Column(db.JSON, nullable=False, default=dict)
    error_code = db.Column(db.String(80))
    response_hash = db.Column(db.String(64))
    __table_args__ = (
        db.UniqueConstraint("operation_id", "stage", "attempt_no"),
        db.CheckConstraint("stage IN ('INTENT','PATIENT','TUTOR','TOKEN_COUNT','EMBEDDING')", name="stage"),
        db.CheckConstraint("status IN ('RESERVED','SENT','SUCCEEDED','FAILED','UNKNOWN','CANCELLED')", name="status"),
        db.CheckConstraint("attempt_no > 0", name="attempt_positive"),
        db.CheckConstraint("reserved_cost_microusd >= 0 AND (actual_cost_microusd IS NULL OR actual_cost_microusd >= 0)", name="costs_nonnegative"),
        db.Index("ix_ai_calls_requested_status", "requested_at", "status"),
    )
