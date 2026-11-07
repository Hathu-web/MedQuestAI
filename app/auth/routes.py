from flask import current_app, flash, g, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user
from werkzeug.exceptions import TooManyRequests

from . import auth
from .forms import LoginForm, PasswordForm, RegistrationForm
from ..security import require_auth_schema, safe_next_url
from ..services.account_service import authenticate, change_password, register_student


@auth.before_request
def auth_database_ready():
    require_auth_schema()


def limit_attempts(scope):
    if request.method != "POST" or not current_app.config["AUTH_RATE_LIMIT_ENABLED"]:
        return
    wait = current_app.extensions["auth_limiter"].consume(
        (request.remote_addr or "local", scope), current_app.config[f"AUTH_{scope.upper()}_LIMIT"],
        current_app.config["AUTH_RATE_WINDOW_SECONDS"])
    if wait:
        raise TooManyRequests(retry_after=wait)


def start_login(user):
    # Không giữ dữ liệu từ phiên khách; sinh CSRF mới sau đăng nhập/đổi mật khẩu.
    session.clear()
    g.pop("csrf_token", None)
    login_user(user, remember=False, fresh=True)
    session.permanent = True


@auth.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.account"))
    limit_attempts("login")
    form = LoginForm()
    if request.method == "GET":
        form.next.data = safe_next_url(request.args.get("next")) or ""
    status = 200
    if form.validate_on_submit():
        user = authenticate(form.email.data, form.password.data)
        if user is not None:
            target = safe_next_url(form.next.data) or url_for("main.account")
            start_login(user)
            return redirect(target)
        form.password.errors.append("Email hoặc mật khẩu không đúng, hoặc tài khoản chưa thể đăng nhập.")
        status = 401
    elif request.method == "POST":
        status = 400
    return render_template("auth/login.html", title="Đăng nhập", active_nav="login", form=form), status


@auth.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.account"))
    limit_attempts("register")
    form = RegistrationForm()
    status = 200
    if form.validate_on_submit():
        try:
            register_student(form.email.data, form.display_name.data, form.password.data)
        except ValueError as exc:
            form.email.errors.append(str(exc))
            status = 400
        else:
            flash("Đã tạo tài khoản học viên. Bạn có thể đăng nhập ngay.", "success")
            return redirect(url_for("auth.login"))
    elif request.method == "POST":
        status = 400
    return render_template("auth/register.html", title="Đăng ký", active_nav="account", form=form), status


@auth.post("/logout")
@login_required
def logout():
    logout_user()
    session.clear()
    g.pop("csrf_token", None)
    flash("Bạn đã đăng xuất.", "info")
    return redirect(url_for("auth.login"))


@auth.route("/password", methods=["GET", "POST"])
@login_required
def password():
    limit_attempts("password")
    form = PasswordForm()
    status = 200
    if form.validate_on_submit():
        try:
            user = change_password(current_user.id, current_user.auth_version,
                                   form.current_password.data, form.password.data)
        except ValueError as exc:
            form.current_password.errors.append(str(exc))
            status = 400
        else:
            start_login(user)
            flash("Đã đổi mật khẩu. Các phiên đăng nhập cũ đã hết hiệu lực.", "success")
            return redirect(url_for("main.account"))
    elif request.method == "POST":
        status = 400
    return render_template("auth/password.html", title="Đổi mật khẩu", active_nav="account", form=form), status
