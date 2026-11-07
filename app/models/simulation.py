from ..extensions import db
from .common import utc_now


class SimulationSession(db.Model):
    __tablename__ = "sessions"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    case_version_id = db.Column(db.Integer, db.ForeignKey("case_versions.id", ondelete="RESTRICT"), nullable=False)
    status = db.Column(db.String(16), nullable=False, default="ACTIVE")
    mode = db.Column(db.String(16), nullable=False, default="PRACTICE")
    state_json = db.Column(db.JSON, nullable=False)
    state_version = db.Column(db.Integer, nullable=False, default=0)
    turn_index = db.Column(db.Integer, nullable=False, default=0)
    assisted = db.Column(db.Integer, nullable=False, default=0)
    start_request_key = db.Column(db.String(100), nullable=False)
    start_input_hash = db.Column(db.String(64), nullable=False)
    started_at = db.Column(db.String(32), nullable=False, default=utc_now)
    ended_at = db.Column(db.String(32))
    __table_args__ = (
        db.UniqueConstraint("user_id", "start_request_key"),
        db.UniqueConstraint("id", "case_version_id"),
        db.UniqueConstraint("id", "user_id"),
        db.CheckConstraint("status IN ('ACTIVE','COMPLETED','ABANDONED')", name="status"),
        db.CheckConstraint("mode IN ('PRACTICE','TEST')", name="mode"),
        db.CheckConstraint("state_version >= 0 AND turn_index BETWEEN 0 AND 20", name="counters"),
        db.CheckConstraint("assisted IN (0,1)", name="assisted"),
        db.CheckConstraint("(status = 'ACTIVE' AND ended_at IS NULL) OR (status != 'ACTIVE' AND ended_at IS NOT NULL)", name="end_time"),
        db.Index("ix_sessions_user_started", "user_id", "started_at"),
    )


class Message(db.Model):
    __tablename__ = "messages"
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("sessions.id", ondelete="RESTRICT"), nullable=False)
    operation_id = db.Column(db.Integer)
    seq_no = db.Column(db.Integer, nullable=False)
    sender = db.Column(db.String(16), nullable=False)
    content_text = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.String(32), nullable=False, default=utc_now)
    __table_args__ = (
        db.ForeignKeyConstraint(["operation_id", "session_id"], ["ai_operations.id", "ai_operations.session_id"], ondelete="RESTRICT"),
        db.UniqueConstraint("session_id", "seq_no"),
        db.UniqueConstraint("operation_id", "sender"),
        db.UniqueConstraint("id", "session_id"),
        db.CheckConstraint("sender IN ('LEARNER','PATIENT')", name="sender"),
        db.CheckConstraint("seq_no > 0", name="sequence_positive"),
        db.CheckConstraint("operation_id IS NOT NULL OR sender = 'PATIENT'", name="opening_patient"),
    )


class SessionEvent(db.Model):
    __tablename__ = "session_events"
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("sessions.id", ondelete="RESTRICT"), nullable=False)
    request_key = db.Column(db.String(100), nullable=False)
    event_code = db.Column(db.String(60), nullable=False)
    event_type = db.Column(db.String(24), nullable=False)
    before_state = db.Column(db.JSON, nullable=False)
    after_state = db.Column(db.JSON, nullable=False)
    evidence_payload_json = db.Column(db.JSON, nullable=False, default=dict)
    created_at = db.Column(db.String(32), nullable=False, default=utc_now)
    __table_args__ = (
        db.UniqueConstraint("session_id", "request_key", "event_code"),
        db.UniqueConstraint("id", "session_id"),
        db.CheckConstraint("event_type IN ('TURN','ACTION','HINT_USED','SESSION_CLOSED')", name="event_type"),
        db.Index("ix_session_events_session_created", "session_id", "created_at"),
    )


class Submission(db.Model):
    __tablename__ = "submissions"
    session_id = db.Column(db.Integer, db.ForeignKey("sessions.id", ondelete="RESTRICT"), primary_key=True)
    summary_json = db.Column(db.JSON, nullable=False)
    submitted_at = db.Column(db.String(32), nullable=False, default=utc_now)
    payload_hash = db.Column(db.String(64), nullable=False)
