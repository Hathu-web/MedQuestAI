from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from . import admin
from .forms import AccountStatusForm
from ..extensions import db
from ..models import User
from ..security import admin_required
from ..services.account_service import set_student_status


@admin.get("/users")
@admin_required
def users():
    page = request.args.get("page", 1, type=int)
    pagination = db.paginate(db.select(User).order_by(User.id), page=max(1, page), per_page=20, error_out=False)
    return render_template("admin/users.html", title="Quản lý tài khoản", active_nav="admin", pagination=pagination)


@admin.route("/users/<int:user_id>/status", methods=["GET", "POST"])
@admin_required
def user_status(user_id):
    target = db.session.get(User, user_id)
    if not target or target.role != "STUDENT" or target.id == current_user.id:
        abort(404)
    form = AccountStatusForm()
    if request.method == "GET":
        desired = request.args.get("status")
        if desired not in {"ACTIVE", "LOCKED"}:
            abort(400)
        form.status.data = desired
        form.expected_status.data = target.status
    if form.validate_on_submit():
        try:
            set_student_status(current_user.id, current_user.auth_version, target.id, form.status.data, form.expected_status.data)
        except (LookupError, PermissionError):
            abort(404)
        except ValueError as exc:
            return render_template("admin/status.html", title="Xác nhận thay đổi", active_nav="admin",
                                   target=target, form=form, error=str(exc)), 409
        flash("Đã cập nhật trạng thái tài khoản học viên.", "success")
        return redirect(url_for("admin.users"))
    if request.method == "POST":
        abort(400)
    return render_template("admin/status.html", title="Xác nhận thay đổi", active_nav="admin", target=target, form=form)
