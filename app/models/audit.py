from ..extensions import db
from .common import utc_now


class AuditLog(db.Model):
    __tablename__ = "audit_log"
    id = db.Column(db.Integer, primary_key=True)
    actor_user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="RESTRICT"))
    entity_type = db.Column(db.String(40), nullable=False)
    entity_id = db.Column(db.String(64), nullable=False)
    action = db.Column(db.String(60), nullable=False)
    occurred_at = db.Column(db.String(32), nullable=False, default=utc_now)
    metadata_json = db.Column(db.JSON, nullable=False, default=dict)
