from uuid import uuid4

from flask import abort, current_app, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from . import simulation
from .forms import ActionForm, AssessmentForm, CloseForm, MessageForm
from ..services.preview_service import patient_profile
from ..security import get_owned_session
from ..services.session_service import public_session
from ..services.conversation_service import perform
from ..services.practice_service import PracticeError
from ..services.assessment_service import maybe_auto_assess, perform_assessment


@simulation.get("/preview/room")
def room():
    if not current_app.config["PREVIEW_ENABLED"]:
        abort(404)
    try:
        patient = patient_profile(request.args.get("patient", "male"))
    except ValueError:
        abort(404)
    return render_template("simulation/room.html", title="Phòng mô phỏng",
                           active_nav="room", patient=patient,
                           max_turns=current_app.config["PREVIEW_MAX_TURNS"],
                           max_length=current_app.config["PREVIEW_MAX_MESSAGE_LENGTH"])


@simulation.get("/sessions/<int:session_id>")
@login_required
def session_detail(session_id):
    return render_session(session_id)


def render_session(session_id, message_form=None, close_form=None, error=None, status=200):
    saved = public_session(get_owned_session(session_id))

    # POST lỗi có thể đã tiêu thụ request_key. Giữ bản nháp/lỗi kiểm tra,
    # nhưng lần bấm Gửi tiếp theo phải dùng mã mới và phiên bản hiện tại.
    # Không tự gửi lại: backend vẫn kiểm tra trùng mã và yêu cầu đang chạy.
    for form in (message_form, close_form):
        if form is not None:
            for name, value in (("request_key", uuid4().hex),
                                ("expected_state_version", saved["state_version"])):
                form[name].data = value
                form[name].raw_data = [str(value)]

    def fresh(form_class, **data):
        # formdata=None: không sao chép POST của form khác vào các form mới.
        return form_class(formdata=None, request_key=uuid4().hex,
                          expected_state_version=saved["state_version"], **data)

    action_forms = [(row, fresh(ActionForm, action_code=row["code"])) for row in saved["actions"]]
    return render_template("simulation/detail.html", title="Lượt thực hành của bạn",
        active_nav="cases", saved=saved, error=error,
        message_form=message_form if message_form is not None else fresh(MessageForm),
        close_form=close_form if close_form is not None else fresh(CloseForm, decision="SUBMIT"),
        assessment_form=fresh(AssessmentForm),
        abandon_form=fresh(CloseForm, decision="ABANDON", summary=""), action_forms=action_forms), status


def process_form(session_id, kind, form):
    get_owned_session(session_id)
    if not form.validate_on_submit():
        error = "Biểu mẫu chưa hợp lệ. Kiểm tra nội dung hoặc tải lại trang."
        status = 400
    else:
        fields = {"request_key", "expected_state_version"}
        fields |= {"TURN": {"text"}, "ACTION": {"action_code"}, "CLOSE": {"decision", "summary"}}[kind]
        payload = {name: form[name].data for name in fields}
        if kind == "CLOSE" and payload["summary"] is None:
            payload["summary"] = ""
        try:
            created = perform(current_user.id, current_user.auth_version, session_id, kind, payload)
            warning = maybe_auto_assess(current_user.id, current_user.auth_version, session_id, kind, payload, created)
        except PracticeError as exc:
            if exc.status in (401, 404):
                raise
            error, status = str(exc), exc.status
        else:
            if warning:
                return render_session(session_id, error=warning)
            return redirect(url_for("simulation.session_detail", session_id=session_id, _anchor="conversation"))
    return render_session(session_id, error=error, status=status,
        message_form=form if kind == "TURN" else None,
        close_form=form if kind == "CLOSE" and form.decision.data == "SUBMIT" else None)


@simulation.post("/sessions/<int:session_id>/messages")
@login_required
def send_message(session_id):
    return process_form(session_id, "TURN", MessageForm())


@simulation.post("/sessions/<int:session_id>/actions")
@login_required
def send_action(session_id):
    return process_form(session_id, "ACTION", ActionForm())


@simulation.post("/sessions/<int:session_id>/close")
@login_required
def close_session(session_id):
    return process_form(session_id, "CLOSE", CloseForm())


@simulation.post("/sessions/<int:session_id>/assessment")
@login_required
def assess_session(session_id):
    get_owned_session(session_id)
    form = AssessmentForm()
    if not form.validate_on_submit():
        return render_session(session_id, error="Biểu mẫu chấm chưa hợp lệ. Tải lại lượt.", status=400)
    try:
        perform_assessment(current_user.id, current_user.auth_version, session_id,
            {name: form[name].data for name in ("request_key", "expected_state_version")})
    except PracticeError as exc:
        if exc.status in (401, 404):
            raise
        return render_session(session_id, error=str(exc), status=exc.status)
    return redirect(url_for("simulation.session_detail", session_id=session_id, _anchor="assessment"))
