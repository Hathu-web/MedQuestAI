"""Ghi hội thoại, hành động và kết thúc lượt trong một giao dịch SQLite."""
from copy import deepcopy
import hashlib
import json
import re

from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from flask import current_app

from ..extensions import db
from ..models import AIOperation, CaseVersion, Message, SessionEvent, SimulationSession, Submission, User
from ..models.common import utc_now
from . import fake_patient
from .practice_service import PracticeError, can_test
from .scenario_engine import action_options, apply_event

MAX_TURNS = 20
MAX_MESSAGE_LENGTH = 2000
MAX_SUMMARY_LENGTH = 4000


def validate_input(kind, payload):
    fields = {"request_key", "expected_state_version"}
    fields |= {"TURN": {"text"}, "ACTION": {"action_code"}, "CLOSE": {"decision", "summary"}}[kind]
    if not isinstance(payload, dict) or set(payload) != fields:
        raise PracticeError("Các trường gửi lên chưa hợp lệ.")
    key, version = payload["request_key"], payload["expected_state_version"]
    if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,100}", key):
        raise PracticeError("Mã yêu cầu không hợp lệ. Tải lại trang.")
    if type(version) is not int or not 0 <= version <= 2_147_483_647:
        raise PracticeError("Phiên bản lượt chưa hợp lệ. Tải lại trang.")
    data = dict(payload)
    if kind == "TURN":
        value = data["text"]
        if not isinstance(value, str) or not value.strip() or len(value) > MAX_MESSAGE_LENGTH:
            raise PracticeError("Nhập câu hỏi từ 1 đến 2.000 ký tự.")
        data["text"] = value.strip()
    elif kind == "ACTION":
        if not isinstance(data["action_code"], str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,59}", data["action_code"]):
            raise PracticeError("Hành động chưa hợp lệ.")
    else:
        if data["decision"] not in ("SUBMIT", "ABANDON"):
            raise PracticeError("Lựa chọn kết thúc chưa hợp lệ.")
        value = data["summary"]
        if not isinstance(value, str) or len(value) > MAX_SUMMARY_LENGTH:
            raise PracticeError("Bản tóm tắt tối đa 4.000 ký tự.")
        data["summary"] = value.strip()
        if data["decision"] == "SUBMIT" and not data["summary"]:
            raise PracticeError("Hãy viết bản tóm tắt trước khi hoàn tất lượt.")
        if data["decision"] == "ABANDON" and data["summary"]:
            raise PracticeError("Bỏ lượt không nhận bản tóm tắt; dùng nút Hoàn tất nếu muốn nộp.")
    return data


def perform(user_id, auth_version, session_id, kind, payload):
    data = validate_input(kind, payload)
    if kind == "TURN" and current_app.config.get("AI_CHAT_ENABLED"):
        from ..ai.service import perform_rag
        return perform_rag(user_id, auth_version, session_id, data)
    digest = hashlib.sha256(json.dumps({"kind": kind, **data}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    db.session.rollback()
    try:
        # Chỉ xử lý nội bộ, không chờ mạng/LLM trong khóa ghi này.
        db.session.execute(text("BEGIN IMMEDIATE"))
        user = db.session.get(User, user_id, populate_existing=True)
        if not user or not user.is_active or user.auth_version != auth_version:
            raise PracticeError("Phiên đăng nhập đã thay đổi. Đăng nhập lại.", 401, "AUTH_REQUIRED")
        item = db.session.get(SimulationSession, session_id, populate_existing=True)
        if (not item or item.user_id != user.id
                or (item.mode == "TEST" and not can_test(user))
                or (item.mode == "PRACTICE" and user.role == "ADMIN")):
            raise PracticeError("Không tìm thấy lượt thực hành.", 404, "SESSION_NOT_FOUND")
        existing = db.session.scalar(db.select(AIOperation).where(
            AIOperation.session_id == item.id, AIOperation.request_key == data["request_key"]))
        if existing:
            if existing.input_hash != digest:
                raise PracticeError("Mã yêu cầu đã được dùng cho nội dung khác. Tải lại trang.", 409, "REQUEST_CONFLICT")
            if existing.status != "SUCCEEDED":
                raise PracticeError("Yêu cầu này chưa hoàn tất. Tải lại trang để kiểm tra.", 409, "OPERATION_PENDING")
            db.session.rollback()
            return False
        if item.status != "ACTIVE":
            raise PracticeError("Lượt đã kết thúc; chỉ có thể đọc lại hội thoại.", 409, "SESSION_CLOSED")
        if item.state_version != data["expected_state_version"]:
            raise PracticeError("Lượt đã thay đổi ở một tab khác. Tải lại trang rồi gửi lại.", 409, "STALE_STATE")
        if kind == "TURN" and item.turn_index >= MAX_TURNS:
            raise PracticeError("Đã đủ 20 lượt hỏi đáp. Hãy viết bản tóm tắt để hoàn tất.", 409, "TURN_LIMIT")

        content = db.session.get(CaseVersion, item.case_version_id).content_json
        if kind == "TURN" and content.get("dialogue", {}).get("mode") == "OPEN_PATIENT":
            raise PracticeError("Ca hội thoại tự do cần bật AI_CHAT_ENABLED và cấu hình LLM thật.",
                                503, "AI_PATIENT_DISABLED")
        before = deepcopy(item.state_json)
        action = None
        if kind == "TURN":
            event = fake_patient.detect_intent(content, data["text"])
        elif kind == "ACTION":
            action = next((row for row in action_options(content, before)
                           if row["action_code"] == data["action_code"]), None)
            if action is None:
                raise PracticeError("Hành động hiện không khả dụng hoặc đã dùng hết.", 409, "ACTION_UNAVAILABLE")
            event = action["event"]
        else:
            event = data["decision"]
        result = apply_event(content, before, event)
        after = result["state"]
        if action:
            uses = after.setdefault("action_uses", {})
            uses[action["action_code"]] = uses.get(action["action_code"], 0) + 1
        if kind == "CLOSE":
            terminal = {row["state_id"] for row in content["states"] if row["terminal"]}
            if after["state_id"] not in terminal:
                raise PracticeError("Ca chưa có luật kết thúc hợp lệ.", 409, "CLOSE_UNAVAILABLE")

        operation = AIOperation(session_id=item.id, request_key=data["request_key"],
            input_hash=digest, kind="TURN" if kind == "TURN" else "ACTION", status="SUCCEEDED",
            expected_state_version=data["expected_state_version"],
            input_payload_json={"provider": "fake", "kind": kind, **data}, finished_at=utc_now())
        db.session.add(operation)
        db.session.flush()
        if kind != "CLOSE":
            answer = action["reply"] if action else fake_patient.reply({
                "intent": event, "facts": result["facts"],
                "opening": content["public"]["opening"], "fallbacks": content["fallbacks"]})
            seq = db.session.scalar(db.select(db.func.max(Message.seq_no)).where(Message.session_id == item.id)) or 0
            learner_text = f"[Hành động] {action['label']}" if action else data["text"]
            for offset, sender, value in ((1, "LEARNER", learner_text), (2, "PATIENT", answer)):
                db.session.add(Message(session_id=item.id, operation_id=operation.id,
                    seq_no=seq + offset, sender=sender, content_text=value))
        item.state_json = after
        item.state_version += 1
        if kind == "TURN":
            item.turn_index += 1
        elif kind == "CLOSE":
            item.status = "COMPLETED" if event == "SUBMIT" else "ABANDONED"
            item.ended_at = utc_now()
            # Trigger của DB yêu cầu sessions đã COMPLETED trước khi INSERT submission.
            db.session.flush()
            if event == "SUBMIT":
                summary = {"text": data["summary"]}
                summary_hash = hashlib.sha256(json.dumps(summary, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
                db.session.add(Submission(session_id=item.id, summary_json=summary, payload_hash=summary_hash))
        db.session.add(SessionEvent(session_id=item.id, request_key=data["request_key"],
            event_code=event or "UNRECOGNIZED", event_type="SESSION_CLOSED" if kind == "CLOSE" else kind,
            before_state=before, after_state=deepcopy(after), evidence_payload_json={
                "provider": "fake", "operation_id": operation.id, "rule_id": result["rule_id"],
                "intent_id": event, "fact_ids": [row["fact_id"] for row in result["facts"]],
                "emitted_events": result["event_codes"]}))
        db.session.commit()
        return True
    except OperationalError as exc:
        db.session.rollback()
        if (getattr(exc.orig, "sqlite_errorcode", 0) & 255) in (5, 6):
            raise PracticeError("Database đang bận. Thử lại cùng yêu cầu sau vài giây.", 503, "DATABASE_BUSY") from exc
        raise
    except Exception:
        db.session.rollback()
        raise
