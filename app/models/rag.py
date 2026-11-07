from ..extensions import db
from .common import utc_now


class AIChunk(db.Model):
    __tablename__ = "ai_chunks"
    id = db.Column(db.Integer, primary_key=True)
    case_version_id = db.Column(db.Integer, db.ForeignKey("case_versions.id", ondelete="RESTRICT"), nullable=False)
    kind = db.Column(db.String(12), nullable=False)
    source_id = db.Column(db.String(40), nullable=False)
    part = db.Column(db.Integer, nullable=False)
    content_text = db.Column(db.Text, nullable=False)
    search_text = db.Column(db.Text, nullable=False)
    source_hash = db.Column(db.String(64), nullable=False)
    embedding_identity = db.Column(db.String(100), nullable=False)
    dimensions = db.Column(db.Integer, nullable=False)
    vector_blob = db.Column(db.LargeBinary, nullable=False)
    created_at = db.Column(db.String(32), nullable=False, default=utc_now)
    __table_args__ = (
        db.UniqueConstraint("case_version_id", "kind", "source_id", "part"),
        db.CheckConstraint("kind IN ('FACT','INTENT')", name="kind"),
        db.CheckConstraint("part >= 0 AND dimensions BETWEEN 1 AND 8192", name="dimensions"),
        db.Index("ix_ai_chunks_case_kind", "case_version_id", "kind"),
    )
