"""Xác thực và quyền dùng chung cho HTML/API; ADMIN không vượt chủ sở hữu."""
from functools import wraps
from urllib.parse import unquote, urlsplit

from flask import abort, current_app, flash, g, redirect, request, session, url_for
from flask_login import current_user, login_required, logout_user
from sqlalchemy import inspect

from .errors import api_error
from .extensions import db, login_manager
from .models import SimulationSession, User


def safe_next_url(value):
    if not isinstance(value, str) or not value or len(value) > 2048:
        return None
    decoded = value
    for _ in range(4):
        decoded = unquote(decoded)
        if "\\" in decoded or any(ord(c) <= 32 or ord(c) == 127 for c in decoded):
            return None
        try:
            parsed = urlsplit(decoded)
        except ValueError:
            return None
        if parsed.scheme or parsed.netloc or not decoded.startswith("/") or decoded.startswith("//"):
            return None
    if "%" in decoded or parsed.path.rstrip("/") in {"/auth/login", "/auth/register", "/auth/logout"}:
        return None
    return decoded


def require_auth_schema():
    # Cache chỉ trong app này, không dùng chung giữa các cấu hình/test.
    if current_app.extensions.get("auth_schema_ready"):
        return
    inspector = inspect(db.engine)
    if "users" not in inspector.get_table_names():
        g.auth_storage_unavailable = True
        abort(503, description="Chưa thiết lập database. Chạy scripts/setup_database.py trong terminal.")
    columns = {col["name"] for col in inspector.get_columns("users")}
    if "auth_version" not in columns:
        g.auth_storage_unavailable = True
        abort(503, description="Database cần cập nhật bước 3. Chạy scripts/upgrade_step3.py trong terminal.")
    current_app.extensions["auth_schema_ready"] = True


def register_security(app):
    login_manager.login_view = "auth.login"
    login_manager.session_protection = "strong"

    @login_manager.user_loader
    def load_user(token):
        # Error template/context processor có thể hỏi current_user lần nữa.
        if g.get("auth_storage_unavailable"):
            return None
        if not isinstance(token, str):
            return None
        parts = token.split(":")
        if len(parts) != 2 or not all(p.isascii() and p.isdigit() and 0 < len(p) <= 18 for p in parts):
            return None
        user_id, version = map(int, parts)
        if user_id < 1 or version < 1:
            return None
        require_auth_schema()
        user = db.session.get(User, user_id)
        return user if user and user.is_active and user.auth_version == version else None

    @login_manager.unauthorized_handler
    def unauthorized():
        if request.path.startswith("/api/"):
            return api_error("AUTH_REQUIRED", "Phiên đăng nhập đã hết hạn hoặc chưa đăng nhập.", 401)
        flash("Vui lòng đăng nhập để tiếp tục.", "info")
        target = safe_next_url(request.full_path.rstrip("?"))
        return redirect(url_for("auth.login", next=target))

    @app.before_request
    def discard_revoked_login():
        if request.endpoint == "static":
            return
        had_login = "_user_id" in session
        if had_login and not current_user.is_authenticated:
            logout_user()
            session.clear()
            g.pop("csrf_token", None)
            if request.path.startswith("/api/"):
                return api_error("AUTH_REQUIRED", "Phiên đăng nhập đã hết hiệu lực. Vui lòng đăng nhập lại.", 401)
            if request.endpoint not in {"auth.login", "auth.register"}:
                flash("Phiên đăng nhập đã hết hiệu lực. Vui lòng đăng nhập lại.", "info")
                return redirect(url_for("auth.login"))


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if current_user.role != "ADMIN":
            abort(404)
        return view(*args, **kwargs)
    return wrapped


def get_owned_session(session_id):
    if not current_user.is_authenticated:
        abort(401)
    item = db.session.scalar(db.select(SimulationSession).where(
        SimulationSession.id == session_id, SimulationSession.user_id == current_user.id))
    if item is None:
        abort(404)
    if current_user.role == "ADMIN" and item.mode != "TEST":
        abort(404)
    if item.mode == "TEST" and current_user.role != "ADMIN" and not current_user.is_test_account:
        abort(404)
    return item
