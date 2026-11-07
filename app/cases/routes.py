from uuid import uuid4

from flask import redirect, render_template, request, url_for
from flask_login import current_user, login_required
from flask_wtf import FlaskForm
from wtforms import HiddenField, SubmitField
from wtforms.validators import AnyOf, InputRequired, Regexp

from . import cases
from ..errors import api_error
from ..services.practice_service import (PracticeError, available_case, can_test, daily_usage,
    default_mode, public_case, start_session, visible_cases)


class StartForm(FlaskForm):
    request_key = HiddenField(validators=[InputRequired(), Regexp(r"^[A-Za-z0-9_-]{16,100}$")])
    mode = HiddenField(validators=[InputRequired(), AnyOf(["PRACTICE", "TEST"])])
    submit = SubmitField("Bắt đầu lượt mới")


@cases.app_errorhandler(PracticeError)
def practice_error(error):
    if request.path.startswith("/api/"):
        body, status = api_error(error.code, str(error), error.status)
    else:
        body, status = render_template("errors/error.html", status=error.status,
            title="Chưa thể bắt đầu lượt", message=str(error)), error.status
    headers = {"Retry-After": str(error.retry_after)} if error.retry_after else {}
    return body, status, headers


@cases.get("/cases")
@login_required
def index():
    return render_template("cases/index.html", title="Thư viện ca", active_nav="cases",
        items=visible_cases(current_user), testing=can_test(current_user))


@cases.route("/cases/<int:version_id>", methods=["GET", "POST"])
@login_required
def detail(version_id):
    form = StartForm()
    if request.method == "POST":
        if not form.validate_on_submit():
            raise PracticeError("Biểu mẫu chưa hợp lệ. Tải lại trang nhiệm vụ và thử lại.")
        identifier, _created = start_session(current_user.id, current_user.auth_version,
            version_id, form.request_key.data, form.mode.data)
        return redirect(url_for("simulation.session_detail", session_id=identifier))
    version = available_case(version_id, current_user)
    form.request_key.data, form.mode.data = uuid4().hex, default_mode(version, current_user)
    return render_template("cases/detail.html", title=version.title, active_nav="cases",
        case=public_case(version), form=form, quota=daily_usage(current_user.id))
