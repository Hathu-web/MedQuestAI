from ..extensions import db
from .common import utc_now


class Case(db.Model):
    __tablename__ = "cases"
    id = db.Column(db.Integer, primary_key=True)
    case_code = db.Column(db.String(40), nullable=False, unique=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at = db.Column(db.String(32), nullable=False, default=utc_now)


class CaseVersion(db.Model):
    __tablename__ = "case_versions"
    id = db.Column(db.Integer, primary_key=True)
    case_id = db.Column(db.Integer, db.ForeignKey("cases.id", ondelete="RESTRICT"), nullable=False)
    version_no = db.Column(db.Integer, nullable=False)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    status = db.Column(db.String(24), nullable=False, default="DRAFT")
    title = db.Column(db.String(200), nullable=False)
    content_json = db.Column(db.JSON, nullable=False)
    review_json = db.Column(db.JSON, nullable=False, default=dict)
    content_hash = db.Column(db.String(64), nullable=False)
    demo_only = db.Column(db.Integer, nullable=False, default=1)
    created_at = db.Column(db.String(32), nullable=False, default=utc_now)
    case = db.relationship("Case", backref=db.backref("versions", lazy="select", passive_deletes="all"))
    __table_args__ = (
        db.UniqueConstraint("case_id", "version_no"),
        db.CheckConstraint("version_no > 0", name="version_positive"),
        db.CheckConstraint("status IN ('DRAFT','PENDING_REVIEW','APPROVED','PUBLISHED','ARCHIVED')", name="status"),
        db.CheckConstraint("demo_only IN (0,1)", name="demo_flag"),
        db.CheckConstraint("status != 'PUBLISHED' OR demo_only = 0", name="no_demo_publish"),
        db.Index("uq_case_versions_one_published", "case_id", unique=True,
                 sqlite_where=db.text("status = 'PUBLISHED'")),
    )


class RubricCriterion(db.Model):
    __tablename__ = "rubric_criteria"
    id = db.Column(db.Integer, primary_key=True)
    case_version_id = db.Column(db.Integer, db.ForeignKey("case_versions.id", ondelete="RESTRICT"), nullable=False)
    criterion_code = db.Column(db.String(40), nullable=False)
    group_code = db.Column(db.String(24), nullable=False)
    weight = db.Column(db.Integer, nullable=False)
    description = db.Column(db.Text, nullable=False)
    levels_json = db.Column(db.JSON, nullable=False)
    sort_no = db.Column(db.Integer, nullable=False)
    version = db.relationship("CaseVersion", backref=db.backref("criteria", order_by="RubricCriterion.sort_no", passive_deletes="all"))
    __table_args__ = (
        db.UniqueConstraint("case_version_id", "criterion_code"),
        db.UniqueConstraint("id", "case_version_id"),
        db.CheckConstraint("weight > 0 AND weight <= 100", name="weight"),
        db.CheckConstraint("sort_no > 0", name="sort_positive"),
        db.CheckConstraint("group_code IN ('CURRENT','RELATED','COMMUNICATION','REASONING','SUMMARY')", name="group_code"),
    )
