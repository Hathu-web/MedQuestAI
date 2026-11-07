"""Bộ bốn ca học phần: nhập, kiểm tra chỉ mục, phát hành nguyên lô có audit.

PUBLISHED nghĩa là mở trong ứng dụng, không phải đã thẩm định chuyên môn.
Các trường review.medical/training được giữ nguyên trạng thái thực tế.
"""
from copy import deepcopy
from pathlib import Path

from flask import current_app
from sqlalchemy import text

from ..ai.embeddings import Embedder
from ..ai.errors import AIError
from ..ai.llm import LLMClient
from ..ai.vectorstore import load_index
from ..extensions import db
from ..models import AuditLog, Case, CaseVersion, RubricCriterion, User
from ..models.common import utc_now
from .case_service import CaseValidationError, load_package, package_hash

BUNDLE = (
    ("MQ_COM_01", 4, "mq_com_01_v4.json"),
    ("MQ_COM_02", 2, "mq_com_02_v2.json"),
    ("MQ_COM_03", 1, "mq_com_03_v1.json"),
    ("MQ_COM_04", 1, "mq_com_04_v1.json"),
)


def curriculum_packages():
    directory = Path(current_app.root_path).parent / "data/curriculum"
    packages = [load_package(directory / filename) for _code, _no, filename in BUNDLE]
    for package, (code, number, _filename) in zip(packages, BUNDLE):
        if (package["case_code"], package["version_no"]) != (code, number) or package["demo_only"]:
            raise CaseValidationError("Mã, phiên bản hoặc phạm vi của bộ bốn ca không khớp.")
    return packages


def require_live_ai():
    cfg = current_app.config
    if not cfg.get("AI_CHAT_ENABLED") or not cfg.get("AI_TUTOR_ENABLED"):
        raise AIError("Bộ ca học phần cần bật AI_CHAT_ENABLED=true và AI_TUTOR_ENABLED=true trong .env.", "CATALOG_AI_DISABLED")
    embedder, client = Embedder(), LLMClient()
    if not client.remote or not embedder.remote:
        raise AIError("Bộ ca học phần cần LLM và embedding thật; không dùng provider demo.", "CATALOG_REQUIRES_LIVE_AI")
    return embedder


def require_admin(email):
    admin = db.session.scalar(db.select(User).where(User.email_normalized == email))
    if not admin or admin.role != "ADMIN" or not admin.is_active:
        raise CaseValidationError("Cần email quản trị viên đang hoạt động; không dùng tên đăng nhập thay email.")
    return admin


def bundle_versions(packages):
    result = []
    for package in packages:
        versions = db.session.scalars(db.select(CaseVersion).join(Case).where(
            Case.case_code == package["case_code"])).all()
        if any(v.version_no > package["version_no"] for v in versions):
            raise CaseValidationError(f"{package['case_code']}: database có phiên bản mới hơn bộ cài; dừng để giữ nội dung của bạn.")
        version = next((v for v in versions if v.version_no == package["version_no"]), None)
        if version is not None:
            # So sánh cả JSON và rubric; hash tự khai trong DB không đủ.
            criteria = db.session.scalars(db.select(RubricCriterion).where(
                RubricCriterion.case_version_id == version.id).order_by(RubricCriterion.sort_no)).all()
            actual = [{"criterion_code": r.criterion_code, "group_code": r.group_code, "weight": r.weight,
                       "description": r.description, **r.levels_json} for r in criteria]
            if (version.content_hash != package_hash(package) or version.content_json != package["content"]
                    or version.title != package["title"] or actual != package["rubric"] or version.demo_only):
                raise CaseValidationError(f"{package['case_code']} v{package['version_no']}: đã có nội dung khác; không ghi đè.")
            if version.status not in ("DRAFT", "PUBLISHED"):
                raise CaseValidationError("Bộ cài không tự mở lại ca đã lưu trữ hoặc thay quy trình duyệt đang có.")
        result.append(version)
    return result


def publish_curriculum(packages, admin_email, embedder):
    """Không gọi mạng trong khóa ghi. Nếu một ca lỗi, không phát hành ca nào."""
    db.session.rollback()
    try:
        db.session.execute(text("BEGIN IMMEDIATE"))
        admin = require_admin(admin_email)
        versions = bundle_versions(packages)
        if any(v is None for v in versions):
            raise CaseValidationError("Chưa nhập đủ bốn ca.")
        for version in versions:
            load_index(version, embedder)
        for version in versions:
            previous = db.session.scalars(db.select(CaseVersion).where(
                CaseVersion.case_id == version.case_id, CaseVersion.id != version.id,
                CaseVersion.status != "ARCHIVED")).all()
            for old in previous:
                old.status = "ARCHIVED"
                db.session.add(AuditLog(actor_user_id=admin.id, entity_type="CASE_VERSION", entity_id=str(old.id),
                    action="CASE_ARCHIVED", metadata_json={"replaced_by": version.id, "history_retained": True}))
            db.session.flush()  # Giải phóng unique one-published trước khi mở bản mới.
            if version.status != "PUBLISHED":
                review = deepcopy(version.review_json)
                review["release"] = {"scope": "COURSEWORK", "released_by_user_id": admin.id,
                                     "released_at": utc_now(), "clinical_approval": False}
                version.review_json, version.status = review, "PUBLISHED"
                db.session.add(AuditLog(actor_user_id=admin.id, entity_type="CASE_VERSION", entity_id=str(version.id),
                    action="COURSEWORK_PUBLISHED", metadata_json={"content_hash": version.content_hash,
                    "scope": "COURSEWORK", "clinical_approval": False}))
        result = [(v.id, v.case.case_code, v.version_no) for v in versions]
        db.session.commit()
        return result
    except Exception:
        db.session.rollback()
        raise
