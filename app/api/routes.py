from flask import abort, current_app, g, jsonify, request
from flask_login import current_user, login_required
from . import api
from ..errors import api_error
from ..services.preview_service import patient_profile, sample_reply
from ..security import get_owned_session
from ..services.session_service import public_session
from ..services.practice_service import PracticeError, start_session
from ..services.conversation_service import perform
from ..services.assessment_service import maybe_auto_assess, perform_assessment


def session_operation(session_id, kind):
    get_owned_session(session_id)
    if not request.is_json:
        return api_error("JSON_REQUIRED", "API cần nội dung JSON.", 415)
    payload = request.get_json(silent=True)
    created = perform(current_user.id, current_user.auth_version, session_id, kind, payload)
    warning = maybe_auto_assess(current_user.id, current_user.auth_version, session_id, kind, payload, created)
    return jsonify(ok=True, data={"created": created, **({"assessment_warning": warning} if warning else {}),
        "session": public_session(get_owned_session(session_id))}, request_id=g.request_id)


@api.post("/sessions/<int:session_id>/messages")
@login_required
def send_message(session_id):
    return session_operation(session_id, "TURN")


@api.post("/sessions/<int:session_id>/actions")
@login_required
def send_action(session_id):
    return session_operation(session_id, "ACTION")


@api.post("/sessions/<int:session_id>/close")
@login_required
def close_session(session_id):
    return session_operation(session_id, "CLOSE")


@api.post("/sessions/<int:session_id>/assessment")
@login_required
def assess_session(session_id):
    get_owned_session(session_id)
    if not request.is_json:
        return api_error("JSON_REQUIRED", "API cần nội dung JSON.", 415)
    created = perform_assessment(current_user.id, current_user.auth_version, session_id, request.get_json(silent=True))
    return jsonify(ok=True, data={"created": created,
        "session": public_session(get_owned_session(session_id))}, request_id=g.request_id)


@api.post("/sessions")
@login_required
def create_session():
    if not request.is_json:
        return api_error("JSON_REQUIRED", "API cần nội dung JSON.", 415)
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or set(payload) != {"case_version_id", "request_key", "mode"}:
        raise PracticeError("Cần đúng ba trường: case_version_id, request_key và mode.")
    identifier, created = start_session(current_user.id, current_user.auth_version,
        payload["case_version_id"], payload["request_key"], payload["mode"])
    return jsonify(ok=True, data={"session_id": identifier, "created": created,
        "session": public_session(get_owned_session(identifier))}, request_id=g.request_id), 201 if created else 200


@api.get("/me")
@login_required
def me():
    return jsonify(ok=True, data={"id":current_user.id, "display_name":current_user.display_name,
        "email":current_user.email_normalized, "role":current_user.role,
        "is_test_account":bool(current_user.is_test_account)}, request_id=g.request_id)


@api.get("/sessions/<int:session_id>/state")
@login_required
def session_state(session_id):
    return jsonify(ok=True, data=public_session(get_owned_session(session_id)), request_id=g.request_id)


@api.get("/health")
def health():
    return jsonify(ok=True, data={"app": "MedQuest AI", "status": "ok",
                                 "stage": current_app.config["BUILD_STAGE"],
                                 "ai_connected": None if current_app.config.get("AI_CHAT_ENABLED") and current_app.config["LLM_PROVIDER"] != "demo" else False,
                                 "ai_configured": current_app.config.get("AI_CHAT_ENABLED", False)}, request_id=g.request_id)


@api.post("/preview/messages")
def preview_message():
    if not current_app.config["PREVIEW_ENABLED"]:
        abort(404)
    if not request.is_json:
        return api_error("JSON_REQUIRED", "Yêu cầu phải có định dạng JSON.", 415)
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or "text" not in payload or not set(payload) <= {"text", "patient_key"}:
        return api_error("INVALID_INPUT", "Chỉ gửi text và patient_key trong danh mục.")
    patient_key = payload.get("patient_key", "male")
    if not isinstance(patient_key, str):
        return api_error("INVALID_PATIENT", "Bệnh nhân xem trước không hợp lệ.")
    try:
        patient_profile(patient_key)
    except ValueError:
        return api_error("INVALID_PATIENT", "Bệnh nhân xem trước không hợp lệ.")
    text = payload["text"]
    if not isinstance(text, str) or not text.strip():
        return api_error("EMPTY_MESSAGE", "Bạn chưa nhập câu hỏi.")
    if len(text) > current_app.config["PREVIEW_MAX_MESSAGE_LENGTH"]:
        return api_error("MESSAGE_TOO_LONG", "Mỗi câu hỏi tối đa 2.000 ký tự.")
    # Mẫu dựng sẵn để kiểm tra giao diện. Không gọi AI, không lưu hội thoại.
    return jsonify(ok=True, data=sample_reply(text, patient_key), request_id=g.request_id)
