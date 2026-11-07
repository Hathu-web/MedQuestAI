"""Thư viện, tạo lượt và dashboard; Patient/Tutor do các service AI phụ trách."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import re

from flask import current_app, url_for
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from ..extensions import db
from ..models import AuditLog, Case, CaseVersion, Evaluation, Message, SimulationSession, User
from .case_service import PORTRAITS


class PracticeError(Exception):
    def __init__(self, message, status=400, code="INVALID_INPUT", retry_after=None):
        super().__init__(message)
        self.status, self.code, self.retry_after = status, code, retry_after


def can_test(user):
    return user.role == "ADMIN" or bool(user.is_test_account)


def default_mode(version, user):
    if version.status == "ARCHIVED":
        return None
    if user.role == "STUDENT" and version.status == "PUBLISHED" and not version.demo_only:
        return "PRACTICE"
    return "TEST" if can_test(user) else None


def public_case(version):
    """Chỉ chọn trường công khai, không đưa facts/rules/rubric ra trình duyệt."""
    content = version.content_json
    patient, public = content["patient"], content["public"]
    return {
        "version_id": version.id, "version_no": version.version_no,
        "code": version.case.case_code, "title": version.title,
        "status": version.status, "demo_only": bool(version.demo_only),
        "patient": {"name": patient["name"], "age": patient["age"], "gender": patient["gender"],
                    "image_url": url_for("static", filename=PORTRAITS[patient["portrait_key"]])},
        "reason": public["reason"], "context": public["context"], "opening": public["opening"],
        "objectives": public["objectives"], "difficulty": public["difficulty"],
        "duration_minutes": public["duration_minutes"],
        "coursework": content.get("delivery", {}).get("scope") == "COURSEWORK",
    }


def visible_cases(user):
    query = db.select(CaseVersion).join(Case).where(CaseVersion.status != "ARCHIVED")
    if not can_test(user):
        query = query.where(CaseVersion.status == "PUBLISHED", CaseVersion.demo_only == 0)
    versions = db.session.scalars(query.order_by(Case.case_code, CaseVersion.version_no.desc())).all()
    # Ưu tiên bản đã phát hành; bản nháp mới không che bản đang học.
    selected = {}
    for version in versions:
        previous = selected.get(version.case_id)
        if previous is None or (version.status == "PUBLISHED" and previous.status != "PUBLISHED"):
            selected[version.case_id] = version
    ordered = sorted(selected.values(), key=lambda v: (v.content_json["public"].get("intro_order", 999), v.case.case_code))
    return [{"case": public_case(v), "mode": default_mode(v, user)} for v in ordered]


def available_case(version_id, user):
    version = db.session.get(CaseVersion, version_id)
    if version is None or default_mode(version, user) is None:
        raise PracticeError("Không tìm thấy ca phù hợp với quyền truy cập.", 404, "CASE_NOT_FOUND")
    return version


def day_window(now=None):
    """Ngày theo giờ Việt Nam; thời gian trong database vẫn là UTC."""
    now = now or datetime.now(timezone.utc)
    local = now.astimezone(timezone(timedelta(hours=7)))
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    utc_text = lambda value: value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    return utc_text(start), utc_text(end), max(1, math.ceil((end - local).total_seconds()))


def daily_usage(user_id):
    start, end, wait = day_window()
    used = db.session.scalar(db.select(db.func.count()).select_from(SimulationSession).where(
        SimulationSession.user_id == user_id,
        SimulationSession.started_at >= start, SimulationSession.started_at < end))
    return {"used": used, "limit": current_app.config.get("SESSION_DAILY_LIMIT", 3), "retry_after": wait}


def start_session(user_id, auth_version, version_id, request_key, mode):
    if type(version_id) is not int or version_id < 1 or mode not in ("PRACTICE", "TEST"):
        raise PracticeError("Ca hoặc chế độ thực hành không hợp lệ.")
    if not isinstance(request_key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,100}", request_key):
        raise PracticeError("Mã bắt đầu không hợp lệ. Tải lại trang nhiệm vụ.")
    payload = json.dumps({"case_version_id": version_id, "mode": mode}, sort_keys=True)
    digest = hashlib.sha256(payload.encode()).hexdigest()

    # Khóa ghi SQLite trước khi đếm quota: hai tab không cùng vượt hạn mức.
    db.session.rollback()
    try:
        db.session.execute(text("BEGIN IMMEDIATE"))
        user = db.session.get(User, user_id, populate_existing=True)
        if not user or not user.is_active or user.auth_version != auth_version:
            raise PracticeError("Phiên đăng nhập đã thay đổi. Vui lòng đăng nhập lại.", 401, "AUTH_REQUIRED")
        existing = db.session.scalar(db.select(SimulationSession).where(
            SimulationSession.user_id == user_id, SimulationSession.start_request_key == request_key))
        if existing:
            if existing.start_input_hash != digest:
                raise PracticeError("Mã bắt đầu đã được dùng cho yêu cầu khác. Tải lại trang nhiệm vụ.", 409, "REQUEST_CONFLICT")
            if (existing.mode == "TEST" and not can_test(user)) or (existing.mode == "PRACTICE" and user.role == "ADMIN"):
                raise PracticeError("Không tìm thấy lượt thực hành.", 404, "SESSION_NOT_FOUND")
            identifier = existing.id
            db.session.rollback()
            return identifier, False

        version = available_case(version_id, user)
        practice_ok = user.role == "STUDENT" and version.status == "PUBLISHED" and not version.demo_only
        if (mode == "TEST" and not can_test(user)) or (mode == "PRACTICE" and not practice_ok):
            raise PracticeError("Không tìm thấy ca phù hợp với chế độ này.", 404, "CASE_NOT_FOUND")
        if version.content_json.get("delivery", {}).get("scope") == "COURSEWORK":
            from .catalog_service import require_live_ai
            from ..ai.vectorstore import load_index
            from ..ai.errors import AIError
            try:
                embedder = require_live_ai()
                load_index(version, embedder)
            except AIError as exc:
                raise PracticeError(str(exc), 503, exc.code) from exc
        usage = daily_usage(user_id)
        if usage["used"] >= usage["limit"]:
            raise PracticeError("Bạn đã dùng hết lượt hôm nay. Có thể tiếp tục lượt cũ hoặc bắt đầu mới sau 00:00 giờ Việt Nam.",
                                429, "DAILY_SESSION_LIMIT", usage["retry_after"])
        item = SimulationSession(user_id=user_id, case_version_id=version.id, mode=mode,
            state_json=deepcopy(version.content_json["initial_state"]), state_version=0, turn_index=0,
            start_request_key=request_key, start_input_hash=digest)
        db.session.add(item)
        db.session.flush()
        opening = version.content_json["public"].get("opening")
        if opening:
            db.session.add(Message(session_id=item.id, seq_no=1, sender="PATIENT", content_text=opening))
        db.session.add(AuditLog(actor_user_id=user_id, entity_type="SESSION", entity_id=str(item.id),
            action="SESSION_STARTED", metadata_json={"case_version_id": version.id, "mode": mode}))
        identifier = item.id
        db.session.commit()
        return identifier, True
    except OperationalError as exc:
        db.session.rollback()
        if (getattr(exc.orig, "sqlite_errorcode", 0) & 255) in (5, 6):
            raise PracticeError("Database đang bận. Hãy thử lại cùng yêu cầu sau vài giây.", 503, "DATABASE_BUSY") from exc
        raise
    except Exception:
        db.session.rollback()
        raise


def dashboard_data(user):
    query = db.select(SimulationSession, CaseVersion.title).join(CaseVersion).where(SimulationSession.user_id == user.id)
    if user.role == "ADMIN":
        query = query.where(SimulationSession.mode == "TEST")
    elif not user.is_test_account:
        query = query.where(SimulationSession.mode == "PRACTICE")
    rows = db.session.execute(query.order_by(SimulationSession.started_at.desc(), SimulationSession.id.desc())).all()
    practice = [item for item, _title in rows if item.mode == "PRACTICE"]

    # Chọn bản VALID mới nhất của mỗi lượt PRACTICE đã hoàn tất.
    evaluations = db.session.scalars(db.select(Evaluation).join(SimulationSession,
        Evaluation.session_id == SimulationSession.id).where(SimulationSession.user_id == user.id,
        SimulationSession.mode == "PRACTICE", SimulationSession.status == "COMPLETED",
        Evaluation.status == "VALID").order_by(Evaluation.evaluation_no.desc())).all() if user.role == "STUDENT" else []
    scores = {}
    for evaluation in evaluations:
        scores.setdefault(evaluation.session_id, evaluation.total_points_x2 / 2)
    return {
        "active_count": sum(item.status == "ACTIVE" for item in practice),
        "closed_count": sum(item.status != "ACTIVE" for item in practice),
        "valid_count": len(scores), "test_count": sum(item.mode == "TEST" for item, _ in rows),
        "active": [(item, title) for item, title in rows if item.status == "ACTIVE"],
        "recent": rows[:10], "scores": scores, "quota": daily_usage(user.id),
    }
