"""Reserve/compute/finalize: không giữ giao dịch khi gọi embedding/LLM."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json

from flask import current_app
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from ..extensions import db
from ..models import AICall, AIOperation, CaseVersion, Evaluation, Message, SessionEvent, SimulationSession, User
from ..models.common import utc_now
from ..services.practice_service import PracticeError, can_test, day_window
from .chunking import digest
from .embeddings import Embedder
from .errors import AIError
from .llm import LLMClient
from .rag import finish_turn, plan_turn
from .vectorstore import load_index
from . import patient_dialogue


def lock():
    db.session.rollback()
    db.session.execute(text("BEGIN IMMEDIATE"))


def owned(user_id, auth_version, session_id):
    user = db.session.get(User, user_id, populate_existing=True)
    if not user or not user.is_active or user.auth_version != auth_version:
        raise PracticeError("Phiên đăng nhập đã thay đổi. Đăng nhập lại.", 401, "AUTH_REQUIRED")
    item = db.session.get(SimulationSession, session_id, populate_existing=True)
    if (not item or item.user_id != user.id or (item.mode == "TEST" and not can_test(user))
            or (item.mode == "PRACTICE" and user.role == "ADMIN")):
        raise PracticeError("Không tìm thấy lượt thực hành.", 404, "SESSION_NOT_FOUND")
    return item


def expire_operations(cfg):
    # Lease dài hơn hai cuộc gọi HTTP tối đa. Kết quả đến muộn phải qua finalize lại.
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=2 * cfg["AI_HTTP_TIMEOUT"] + 60)).isoformat(timespec="microseconds").replace("+00:00", "Z")
    rows = db.session.scalars(db.select(AIOperation).where(
        AIOperation.status == "RUNNING", AIOperation.started_at < cutoff)).all()
    for operation in rows:
        operation.status, operation.finished_at = "FAILED", utc_now()
        if operation.evaluation_id:
            evaluation = db.session.get(Evaluation, operation.evaluation_id)
            if evaluation and evaluation.status == "PROCESSING":
                evaluation.status = "ERROR"
                evaluation.feedback_json = {"error_code": "AI_EXPIRED", "message": "Lần chấm đã hết thời gian. Bạn có thể chủ động thử lại."}
        db.session.execute(db.update(AICall).where(AICall.operation_id == operation.id,
            AICall.status.in_(["SENT", "RESERVED"])).values(status="UNKNOWN", error_code="AI_EXPIRED"))
    db.session.flush()
    return len(rows)


def reserve(user_id, auth_version, session_id, data, embedder, cfg):
    # Cùng công thức với bước 5: đổi chế độ AI không làm gửi lại tin đã thành công.
    input_hash = hashlib.sha256(json.dumps({"kind": "TURN", **data}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    lock()
    expire_operations(cfg)
    item = owned(user_id, auth_version, session_id)
    existing = db.session.scalar(db.select(AIOperation).where(
        AIOperation.session_id == item.id, AIOperation.request_key == data["request_key"]))
    if existing:
        if existing.input_hash != input_hash:
            raise PracticeError("Mã yêu cầu đã dùng cho nội dung khác. Tải lại lượt.", 409, "REQUEST_CONFLICT")
        if existing.status == "SUCCEEDED":
            db.session.commit()
            return None
        code = "AI_BUSY" if existing.status == "RUNNING" else "AI_PREVIOUS_FAILED"
        raise PracticeError("Yêu cầu đang xử lý hoặc đã thất bại. Tải lại để xem lịch sử trước khi gửi yêu cầu mới.", 409, code)
    if item.status != "ACTIVE":
        raise PracticeError("Lượt đã kết thúc.", 409, "SESSION_CLOSED")
    if item.state_version != data["expected_state_version"]:
        raise PracticeError("Lượt đã thay đổi ở tab khác. Tải lại trang.", 409, "STALE_STATE")
    if item.turn_index >= 20:
        raise PracticeError("Đã đủ 20 lượt hỏi đáp. Hãy hoàn tất bản tóm tắt.", 409, "TURN_LIMIT")
    if db.session.scalar(db.select(AIOperation.id).where(AIOperation.status == "RUNNING")):
        raise PracticeError("Một yêu cầu AI khác đang xử lý. Vui lòng thử lại sau.", 503, "AI_BUSY")
    start, end, wait = day_window()
    count = db.session.scalar(db.select(db.func.count()).select_from(AICall).where(
        AICall.requested_at >= start, AICall.requested_at < end))
    worst_case = int(embedder.remote) + int(cfg["LLM_PROVIDER"] != "demo")
    if count + worst_case > cfg["AI_DAILY_CALL_LIMIT"]:
        raise PracticeError("Đã đạt giới hạn cuộc gọi AI hôm nay. Thử lại sau 00:00 giờ Việt Nam.", 429, "AI_DAILY_LIMIT", wait)
    version = db.session.get(CaseVersion, item.case_version_id)
    if version.content_json.get("delivery", {}).get("scope") == "COURSEWORK":
        from ..services.catalog_service import require_live_ai
        require_live_ai()
    rows = load_index(version, embedder)
    snapshot = {"content": deepcopy(version.content_json), "content_hash": version.content_hash,
        "before": deepcopy(item.state_json), "state_version": item.state_version,
        "case_version_id": version.id, "case_code": version.case.case_code, "version_no": version.version_no,
        "rows": rows, "session_id": item.id, "user_id": user_id, "auth_version": auth_version}
    if patient_dialogue.enabled(version.content_json):
        if cfg["LLM_PROVIDER"] == "demo":
            raise AIError("Ca hội thoại tự do cần LLM thật. Kiểm tra LLM_PROVIDER.", "AI_PATIENT_REQUIRES_LLM")
        messages = db.session.scalars(db.select(Message).where(Message.session_id == item.id)
            .order_by(Message.seq_no.desc()).limit(12)).all()
        snapshot["history"] = patient_dialogue.recent_history([
            {"sender": m.sender, "text": m.content_text} for m in reversed(messages)])
    operation = AIOperation(session_id=item.id, request_key=data["request_key"], input_hash=input_hash,
        kind="TURN", status="RUNNING", expected_state_version=item.state_version,
        input_payload_json={"provider": "rag", "embedding": embedder.identity, **data})
    db.session.add(operation)
    db.session.flush()
    snapshot["operation_id"] = operation.id
    db.session.commit()
    return snapshot


def tracked_call(snapshot, stage, provider, model, callback):
    lock()
    operation = db.session.get(AIOperation, snapshot["operation_id"])
    if not operation or operation.status != "RUNNING":
        raise AIError("Yêu cầu đã hết hiệu lực. Tải lại lượt.", "AI_OPERATION_EXPIRED", 409)
    call = AICall(operation_id=operation.id, stage=stage, attempt_no=1, status="SENT",
        configuration_json={"provider": provider, "model": model})
    db.session.add(call)
    db.session.flush()
    identifier = call.id
    db.session.commit()
    try:
        result = callback()  # Không có transaction mở ở đây.
    except AIError as exc:
        lock()
        call = db.session.get(AICall, identifier)
        call.status = "UNKNOWN" if exc.uncertain else "FAILED"
        call.error_code = exc.code
        db.session.commit()
        raise
    lock()
    call = db.session.get(AICall, identifier)
    call.status = "SUCCEEDED"
    if isinstance(result, dict):
        call.usage_json = result.get("usage", {})
        call.response_hash = digest(result.get("answer", ""))
    db.session.commit()
    return result


def mark_failure(identifier, status="FAILED"):
    lock()
    operation = db.session.get(AIOperation, identifier)
    if operation and operation.status == "RUNNING":
        operation.status, operation.finished_at = status, utc_now()
        db.session.execute(db.update(AICall).where(AICall.operation_id == identifier,
            AICall.status == "SENT").values(status="UNKNOWN", error_code="AI_INTERRUPTED"))
    db.session.commit()


def finalize(snapshot, data, result):
    lock()
    operation = db.session.get(AIOperation, snapshot["operation_id"])
    if not operation or operation.status != "RUNNING":
        raise PracticeError("Yêu cầu AI đã hết hiệu lực. Tải lại lượt.", 409, "AI_OPERATION_EXPIRED")
    item = owned(snapshot["user_id"], snapshot["auth_version"], snapshot["session_id"])
    version = db.session.get(CaseVersion, snapshot["case_version_id"])
    if (item.status != "ACTIVE" or item.state_version != snapshot["state_version"]
            or item.state_json != snapshot["before"] or version.content_hash != snapshot["content_hash"]
            or version.content_json != snapshot["content"]):
        raise PracticeError("Lượt hoặc ca đã thay đổi khi chờ AI. Kết quả cũ chưa được ghi vào hội thoại.", 409, "STALE_STATE")
    seq = db.session.scalar(db.select(db.func.max(Message.seq_no)).where(Message.session_id == item.id)) or 0
    for offset, sender, value in ((1, "LEARNER", data["text"]), (2, "PATIENT", result["answer"])):
        db.session.add(Message(session_id=item.id, operation_id=operation.id, seq_no=seq + offset,
                               sender=sender, content_text=value))
    item.state_json, item.state_version, item.turn_index = result["after"], item.state_version + 1, item.turn_index + 1
    evidence = {
            "provider": "rag", "operation_id": operation.id, "reply_mode": result["mode"], "sources": result["sources"],
            "intent_id": result["intent"], "rule_id": result["rule_id"], "emitted_events": result["events"]}
    if result.get("answer_kind"):
        evidence["answer_kind"] = result["answer_kind"]
    db.session.add(SessionEvent(session_id=item.id, request_key=data["request_key"], event_code=result["intent"] or "UNRECOGNIZED",
        event_type="TURN", before_state=snapshot["before"], after_state=result["after"], evidence_payload_json=evidence))
    operation.status, operation.finished_at = "SUCCEEDED", utc_now()
    db.session.commit()


def perform_rag(user_id, auth_version, session_id, data):
    snapshot = None
    try:
        cfg = dict(current_app.config)
        embedder, client = Embedder(cfg), LLMClient(cfg)
        snapshot = reserve(user_id, auth_version, session_id, data, embedder, cfg)
        if snapshot is None:
            return False
        open_patient = patient_dialogue.enabled(snapshot["content"])
        queries = (patient_dialogue.retrieval_queries(data["text"], snapshot["history"])
                   if open_patient else [data["text"]])
        embed = lambda: embedder.embed(queries)
        vectors = (tracked_call(snapshot, "EMBEDDING", embedder.provider, embedder.model, embed)
                   if embedder.remote else embed())
        if open_patient:
            plan = patient_dialogue.plan_patient_turn(snapshot, data["text"], vectors, cfg)
            content = snapshot["content"]
            answer = lambda: client.patient_answer(data["text"], content["patient"], plan["hits"],
                plan["history"], content["dialogue"], plan["state"], content["states"])
            response = tracked_call(snapshot, "PATIENT", client.provider, cfg["LLM_MODEL"], answer)
            result = patient_dialogue.finish_patient_turn(snapshot, plan, response)
            finalize(snapshot, data, result)
            return True
        vector = vectors[0]
        plan = plan_turn(snapshot, data["text"], vector, cfg)
        response = None
        if plan["hits"]:
            answer = lambda: client.answer(data["text"], snapshot["content"]["patient"], plan["hits"])
            response = (tracked_call(snapshot, "PATIENT", client.provider, cfg["LLM_MODEL"], answer)
                        if client.remote else answer())
        result = finish_turn(snapshot, plan, response)
        finalize(snapshot, data, result)
        return True
    except Exception as exc:
        db.session.rollback()
        if snapshot:
            try:
                mark_failure(snapshot["operation_id"], "CONFLICT" if isinstance(exc, PracticeError) and exc.status in (401, 404, 409) else "FAILED")
            except OperationalError:
                db.session.rollback()  # Lease sẽ giải phóng yêu cầu nếu DB còn bận.
        if isinstance(exc, AIError):
            raise PracticeError(str(exc), exc.status, exc.code) from exc
        if isinstance(exc, OperationalError) and (getattr(exc.orig, "sqlite_errorcode", 0) & 255) in (5, 6):
            raise PracticeError("Database đang bận. Tải lại lượt trước khi thử lại.", 503, "DATABASE_BUSY") from exc
        raise
