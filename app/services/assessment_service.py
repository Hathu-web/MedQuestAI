"""Chấm sau nộp bài: snapshot DB -> LLM ngoài transaction -> xác minh -> lưu điểm."""
from copy import deepcopy
import json
import re

from flask import current_app
from sqlalchemy.exc import OperationalError

from ..extensions import db
from ..models import AICall, AIOperation, CaseVersion, Evaluation, EvaluationItem, Evidence, Message, RubricCriterion, SessionEvent, Submission
from ..models.common import utc_now
from ..ai.chunking import digest
from ..ai.errors import AIError
from ..ai.llm import LLMClient
from ..ai.service import expire_operations, lock, mark_failure, owned, tracked_call
from ..ai.tutor import PROMPT_VERSION, build_messages, validate_result
from ..ai.settings import validate_settings
from .practice_service import PracticeError, day_window


def validate_request(data):
    if not isinstance(data, dict) or set(data) != {"request_key", "expected_state_version"}:
        raise PracticeError("Yêu cầu chấm cần mã gửi và phiên bản lượt.")
    if not isinstance(data["request_key"], str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,100}", data["request_key"]):
        raise PracticeError("Mã yêu cầu chấm không hợp lệ.")
    if type(data["expected_state_version"]) is not int or data["expected_state_version"] < 0:
        raise PracticeError("Phiên bản lượt không hợp lệ.")


def assessment_input(item):
    submission = db.session.get(Submission, item.id)
    if item.status != "COMPLETED" or submission is None:
        raise PracticeError("Chỉ chấm lượt đã nộp tổng kết; không chấm lượt đang dở hoặc đã bỏ.", 409, "ASSESSMENT_NOT_READY")
    version = db.session.get(CaseVersion, item.case_version_id)
    criteria = db.session.scalars(db.select(RubricCriterion).where(
        RubricCriterion.case_version_id == version.id).order_by(RubricCriterion.sort_no, RubricCriterion.id)).all()
    rubric = [{"id": row.id, "criterion_code": row.criterion_code, "group_code": row.group_code,
               "weight": row.weight, "description": row.description,
               "levels": deepcopy(row.levels_json["levels"]),
               "evidence_sources": list(row.levels_json["evidence_sources"])} for row in criteria]
    if not rubric or sum(row["weight"] for row in rubric) != 100:
        raise PracticeError("Rubric của ca cần đủ 100 điểm trước khi chấm.", 409, "TUTOR_RUBRIC_INVALID")
    messages = db.session.scalars(db.select(Message).where(Message.session_id == item.id).order_by(Message.seq_no)).all()
    events = db.session.scalars(db.select(SessionEvent).where(SessionEvent.session_id == item.id,
        SessionEvent.event_type == "ACTION").order_by(SessionEvent.id)).all()
    actions = {event.evidence_payload_json.get("operation_id"): event for event in events}
    sources, transcript, action_rows = {}, [], []
    for message in messages:
        evidence_id = None
        if message.sender == "LEARNER":
            if message.operation_id in actions:
                event = actions[message.operation_id]
                evidence_id = f"A{event.id}"
                source = {"kind": "ACTION", "text": message.content_text, "event_id": event.id}
                action_rows.append({"source_id": evidence_id, "text": source["text"]})
            else:
                evidence_id = f"M{message.id}"
                source = {"kind": "LEARNER_MESSAGE", "text": message.content_text, "message_id": message.id}
            sources[evidence_id] = source
        transcript.append({"seq": message.seq_no, "speaker": message.sender,
                           "text": message.content_text, "evidence_source": evidence_id})
    summary_id = f"S{item.id}"
    summary = submission.summary_json.get("text", "")
    sources[summary_id] = {"kind": "SUBMISSION", "text": summary, "submission_session_id": item.id}
    revealed = set(item.state_json.get("revealed_fact_ids", []))
    facts = [{key: fact[key] for key in ("fact_id", "topic", "value", "knowledge")}
             for fact in version.content_json["facts"] if fact["fact_id"] in revealed]
    payload = {"RUBRIC": [{k: v for k, v in row.items() if k != "id"} for row in rubric],
               "HOI_THOAI": transcript, "HANH_DONG": action_rows,
               "TONG_KET": {"source_id": summary_id, "text": summary},
               "DU_KIEN_DA_KHAI_THAC": facts, "CO_HO_TRO": bool(item.assisted)}
    snapshot = {"payload": payload, "sources": sources, "rubric": rubric,
                "case_version_id": version.id, "content_hash": version.content_hash,
                "submission_hash": submission.payload_hash, "state_version": item.state_version}
    snapshot["input_hash"] = digest(snapshot)
    return snapshot


def reserve(user_id, auth_version, session_id, data, cfg):
    lock()
    expire_operations(cfg)
    item = owned(user_id, auth_version, session_id)
    request_hash = digest({"kind": "ASSESSMENT", **data})
    prior = db.session.scalar(db.select(AIOperation).where(AIOperation.session_id == session_id,
        AIOperation.request_key == data["request_key"]))
    if prior:
        if prior.input_hash != request_hash or prior.kind != "ASSESSMENT":
            raise PracticeError("Mã yêu cầu đã dùng cho nội dung khác.", 409, "REQUEST_CONFLICT")
        if prior.status == "SUCCEEDED":
            db.session.commit()
            return None
        raise PracticeError("Lần chấm này đang xử lý hoặc đã thất bại. Tải lại để xem kết quả.", 409, "ASSESSMENT_ALREADY_REQUESTED")
    if item.state_version != data["expected_state_version"]:
        raise PracticeError("Lượt đã thay đổi. Tải lại trước khi chấm.", 409, "STALE_STATE")
    snapshot = assessment_input(item)
    latest = db.session.scalar(db.select(Evaluation).where(Evaluation.session_id == session_id)
        .order_by(Evaluation.evaluation_no.desc()))
    if latest and latest.status in ("VALID", "NEEDS_REVIEW"):
        db.session.commit()
        return None  # Không chấm lặp để tìm một điểm cao hơn.
    attempts = latest.evaluation_no if latest else 0
    if attempts >= cfg["AI_TUTOR_MAX_ATTEMPTS"]:
        raise PracticeError("Đã đạt số lần chấm của lượt này. Giữ hồ sơ để người hướng dẫn xem lại.", 429, "TUTOR_ATTEMPT_LIMIT")
    if db.session.scalar(db.select(AIOperation.id).where(AIOperation.status == "RUNNING")):
        raise PracticeError("Một yêu cầu AI đang xử lý. Thử chấm sau khi yêu cầu đó hoàn tất.", 503, "AI_BUSY")
    start, end, wait = day_window()
    count = db.session.scalar(db.select(db.func.count()).select_from(AICall).where(
        AICall.requested_at >= start, AICall.requested_at < end))
    if count >= cfg["AI_DAILY_CALL_LIMIT"]:
        raise PracticeError("Đã đạt hạn mức gọi AI hôm nay; tổng kết đã được lưu.", 429, "AI_DAILY_LIMIT", wait)
    if len(json.dumps(snapshot["payload"], ensure_ascii=False)) > cfg["AI_TUTOR_MAX_CONTEXT_CHARS"]:
        raise PracticeError("Hồ sơ vượt giới hạn chấm; chưa gửi bản bị cắt thiếu cho AI.", 413, "TUTOR_CONTEXT_LIMIT")
    evaluation = Evaluation(session_id=session_id, case_version_id=item.case_version_id,
        evaluation_no=attempts + 1, status="PROCESSING", input_hash=snapshot["input_hash"],
        config_json={"prompt_version": PROMPT_VERSION, "provider": cfg["LLM_PROVIDER"],
                     "model": cfg["LLM_MODEL"], "rubric": snapshot["rubric"]})
    db.session.add(evaluation)
    db.session.flush()
    operation = AIOperation(session_id=session_id, evaluation_id=evaluation.id,
        request_key=data["request_key"], input_hash=request_hash, kind="ASSESSMENT", status="RUNNING",
        expected_state_version=item.state_version,
        input_payload_json={"provider": "llm_tutor", "snapshot_hash": snapshot["input_hash"]})
    db.session.add(operation)
    db.session.flush()
    snapshot.update(session_id=session_id, user_id=user_id, auth_version=auth_version,
                    operation_id=operation.id, evaluation_id=evaluation.id)
    db.session.commit()
    return snapshot


def finalize(snapshot, result):
    lock()
    item = owned(snapshot["user_id"], snapshot["auth_version"], snapshot["session_id"])
    operation = db.session.get(AIOperation, snapshot["operation_id"])
    evaluation = db.session.get(Evaluation, snapshot["evaluation_id"])
    if not operation or operation.status != "RUNNING" or evaluation.status != "PROCESSING":
        raise PracticeError("Lần chấm đã hết hiệu lực; không lưu kết quả đến muộn.", 409, "AI_OPERATION_EXPIRED")
    if assessment_input(item)["input_hash"] != snapshot["input_hash"]:
        raise PracticeError("Hồ sơ hoặc rubric đã thay đổi khi chờ AI; chưa ghi điểm.", 409, "STALE_ASSESSMENT")
    criteria = {row["criterion_code"]: row for row in snapshot["rubric"]}
    suggestions = {}
    for row in result["items"]:
        criterion = criteria[row["criterion_code"]]
        grade = EvaluationItem(evaluation_id=evaluation.id, criterion_id=criterion["id"],
            session_id=item.id, case_version_id=item.case_version_id, level=row["level"],
            points_x2=row["points_x2"], reason_text=row["reason"])
        db.session.add(grade)
        db.session.flush()
        suggestions[row["criterion_code"]] = row["suggestion"]
        for proof in row["evidence"]:
            source = snapshot["sources"][proof["source_id"]]
            references = {key: source[key] for key in ("message_id", "event_id", "submission_session_id") if key in source}
            db.session.add(Evidence(item_id=grade.id, session_id=item.id, quote_text=proof["quote"],
                field_path="summary_json.text" if source["kind"] == "SUBMISSION" else None,
                start_offset=proof["start"], end_offset=proof["end"], **references))
    evaluation.status, evaluation.total_points_x2 = result["status"], result["total_points_x2"]
    evaluation.feedback_json = {"suggestions": suggestions, "reference_only": True}
    operation.status, operation.finished_at = "SUCCEEDED", utc_now()
    db.session.commit()


def perform_assessment(user_id, auth_version, session_id, data):
    validate_request(data)
    snapshot = None
    try:
        cfg = dict(current_app.config)
        validate_settings(cfg)
        if not cfg["AI_TUTOR_ENABLED"]:
            raise PracticeError("AI Tutor chưa bật. Tổng kết vẫn được lưu.", 503, "TUTOR_DISABLED")
        client = LLMClient(cfg)
        if not client.remote:
            raise PracticeError("AI Tutor cần LLM thật; không tạo điểm từ phản hồi mẫu.", 503, "TUTOR_REQUIRES_LLM")
        snapshot = reserve(user_id, auth_version, session_id, data, cfg)
        if snapshot is None:
            return False
        def call():
            raw, usage = client.complete(build_messages(snapshot["payload"]),
                max_output_tokens=cfg["AI_TUTOR_MAX_OUTPUT_TOKENS"])
            result = validate_result(raw, snapshot["rubric"], snapshot["sources"])
            return {**result, "usage": usage, "answer": json.dumps(result, ensure_ascii=False, sort_keys=True)}
        result = tracked_call(snapshot, "TUTOR", cfg["LLM_PROVIDER"], cfg["LLM_MODEL"], call)
        finalize(snapshot, result)
        return True
    except Exception as exc:
        db.session.rollback()
        if snapshot:
            try:
                mark_failure(snapshot["operation_id"])
                lock()
                evaluation = db.session.get(Evaluation, snapshot["evaluation_id"])
                if evaluation and evaluation.status == "PROCESSING":
                    evaluation.status = "ERROR"
                    evaluation.feedback_json = {"error_code": getattr(exc, "code", "TUTOR_ERROR"),
                        "message": str(exc) if isinstance(exc, (AIError, PracticeError)) else "Chưa lưu được kết quả chấm. Tổng kết vẫn còn."}
                db.session.commit()
            except OperationalError:
                db.session.rollback()
        if isinstance(exc, AIError):
            raise PracticeError(str(exc), exc.status, exc.code) from exc
        if isinstance(exc, OperationalError):
            raise PracticeError("Database đang bận; tổng kết đã lưu, chưa chốt điểm.", 503, "DATABASE_BUSY") from exc
        if isinstance(exc, PracticeError):
            raise
        raise PracticeError("Chưa hoàn tất chấm điểm. Tổng kết vẫn được lưu; quản trị viên cần kiểm tra lỗi.",
                            500, "TUTOR_INTERNAL") from exc


def maybe_auto_assess(user_id, auth_version, session_id, kind, payload, created):
    if not (created and kind == "CLOSE" and payload.get("decision") == "SUBMIT"
            and current_app.config["AI_TUTOR_ENABLED"]):
        return None
    try:
        perform_assessment(user_id, auth_version, session_id, {
            "request_key": "tutor-" + digest(payload["request_key"]),
            "expected_state_version": payload["expected_state_version"] + 1})
    except PracticeError as exc:
        if exc.status in (401, 404):
            raise
        return "Tổng kết đã được lưu. " + str(exc)
    return None


def public_assessment(item):
    """Chỉ gọi sau get_owned_session; không trả prompt, rubric ẩn hay khóa cấu hình."""
    latest = db.session.scalar(db.select(Evaluation).where(Evaluation.session_id == item.id)
        .order_by(Evaluation.evaluation_no.desc()))
    enabled = current_app.config["AI_TUTOR_ENABLED"]
    result = {"enabled": enabled, "status": "NOT_STARTED", "score": None, "items": [],
              "can_request": enabled and item.status == "COMPLETED", "message": ""}
    if not latest:
        return result
    status = latest.status
    if status == "PROCESSING":
        from datetime import datetime, timezone
        operation = db.session.scalar(db.select(AIOperation).where(AIOperation.evaluation_id == latest.id))
        started = datetime.fromisoformat(operation.started_at.replace("Z", "+00:00")) if operation else None
        if started and (datetime.now(timezone.utc) - started).total_seconds() > 2 * current_app.config["AI_HTTP_TIMEOUT"] + 60:
            status = "ERROR"  # GET không ghi DB; POST tiếp theo dọn lease trước khi reserve.
            result["message"] = "Lần chấm đã hết thời gian. Bạn có thể chủ động thử lại."
    result.update(status=status, number=latest.evaluation_no, created_at=latest.created_at,
        score=latest.total_points_x2 / 2 if latest.status == "VALID" else None,
        can_request=enabled and status == "ERROR" and latest.evaluation_no < current_app.config["AI_TUTOR_MAX_ATTEMPTS"])
    result["message"] = result["message"] or latest.feedback_json.get("message", "")
    if status not in ("VALID", "NEEDS_REVIEW"):
        return result
    rubric = {row["id"]: row for row in latest.config_json.get("rubric", [])}
    rows = db.session.scalars(db.select(EvaluationItem).where(EvaluationItem.evaluation_id == latest.id)
        .order_by(EvaluationItem.id)).all()
    for row in rows:
        criterion = rubric.get(row.criterion_id)
        if not criterion:
            continue
        evidence = db.session.scalars(db.select(Evidence).where(Evidence.item_id == row.id).order_by(Evidence.id)).all()
        result["items"].append({"code": criterion["criterion_code"], "description": criterion["description"],
            "weight": criterion["weight"], "level": row.level,
            "points": None if row.points_x2 is None else row.points_x2 / 2, "reason": row.reason_text,
            "suggestion": latest.feedback_json.get("suggestions", {}).get(criterion["criterion_code"], ""),
            "evidence": [{"quote": proof.quote_text,
                "label": "Tin nhắn của bạn" if proof.message_id else "Hành động đã thực hiện" if proof.event_id else "Bản tổng kết"}
                for proof in evidence]})
    return result
