"""Application Factory: lắp ghép cấu hình, extensions và Blueprint."""
from pathlib import Path
import secrets
from uuid import uuid4
from datetime import datetime, timedelta, timezone

from flask import Flask, g
from sqlalchemy import event

from config import BASE_DIR, config, environment_values
from .extensions import csrf, db, login_manager, migrate


def create_app(config_name=None, config_overrides=None, *, instance_path=None):
    values = environment_values()
    name = config_name or values.get("MEDQUEST_ENV") or "development"
    if name == "default":
        name = "development"
    if name not in config:
        raise ValueError("MEDQUEST_ENV phải là development, testing, demo hoặc production.")

    configured_instance = values.get("MEDQUEST_INSTANCE_PATH") if name != "testing" else None
    private_dir = Path(instance_path or configured_instance or BASE_DIR / "instance").resolve()
    app = Flask(__name__, instance_relative_config=True, instance_path=str(private_dir))
    app.config.from_object(config[name])
    app.config["ENVIRONMENT"] = name

    # Test không dùng SECRET_KEY hoặc DB thật lấy từ môi trường máy.
    if name != "testing":
        if values.get("SECRET_KEY"):
            app.config["SECRET_KEY"] = values["SECRET_KEY"]
        db_key = {"development": "DEV_DATABASE_URL", "demo": "DEMO_DATABASE_URL", "production": "DATABASE_URL"}[name]
        if values.get(db_key):
            app.config["SQLALCHEMY_DATABASE_URI"] = values[db_key]
        if name == "production":
            flag = str(values.get("SESSION_COOKIE_SECURE", "true")).lower()
            if flag not in ("true", "false", "1", "0"):
                raise ValueError("SESSION_COOKIE_SECURE cần true hoặc false.")
            app.config["SESSION_COOKIE_SECURE"] = flag in ("true", "1")
            hosts = values.get("TRUSTED_HOSTS", "localhost,127.0.0.1,[::1]")
            app.config["TRUSTED_HOSTS"] = [host.strip() for host in hosts.split(",") if host.strip()]
            if not app.config["TRUSTED_HOSTS"]:
                raise ValueError("Production cần TRUSTED_HOSTS.")
    from .ai.settings import configure_ai
    configure_ai(app, values if name != "testing" else {})
    if config_overrides:
        app.config.update(config_overrides)

    key = app.config.get("SECRET_KEY")
    if name in ("demo", "production") and (not key or len(key) < 32):
        raise ValueError("Demo/production cần SECRET_KEY riêng, ít nhất 32 ký tự.")
    if not key:
        app.config["SECRET_KEY"] = secrets.token_urlsafe(32)
        app.logger.warning("Đang dùng khóa development tạm. Chạy scripts/setup_local.py để tạo .env.")
    private_dir.mkdir(parents=True, exist_ok=True)

    @app.before_request
    def assign_request_id():
        g.request_id = uuid4().hex

    db.init_app(app)
    migrate.init_app(app, db, render_as_batch=True)
    login_manager.init_app(app)

    # Đăng ký metadata, KHÔNG gọi create_all; schema do migrations quản lý.
    from . import models

    from .security import register_security
    from .services.auth_limiter import AuthLimiter
    app.extensions["auth_limiter"] = AuthLimiter()
    register_security(app)
    csrf.init_app(app)

    with app.app_context():
        if db.engine.dialect.name == "sqlite":
            @event.listens_for(db.engine, "connect")
            def enable_sqlite_foreign_keys(connection, _record):
                cursor = connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()

    from .main import main
    from .simulation import simulation
    from .api import api
    from .auth import auth
    from .admin import admin
    from .cases import cases
    app.register_blueprint(main)
    app.register_blueprint(simulation)
    app.register_blueprint(api, url_prefix="/api/v1")
    app.register_blueprint(auth, url_prefix="/auth")
    app.register_blueprint(admin, url_prefix="/admin")
    app.register_blueprint(cases)

    from .errors import register_error_handlers
    from .cli import register_commands
    register_error_handlers(app)
    register_commands(app)
    from .ai import register_ai
    register_ai(app)
    from .catalog import catalog
    app.register_blueprint(catalog)

    @app.context_processor
    def shared_template_data():
        return {"app_name": app.config["APP_NAME"], "build_stage": app.config["BUILD_STAGE"]}

    @app.template_filter("vietnam_time")
    def vietnam_time(value):
        if not value:
            return "—"
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.astimezone(timezone(timedelta(hours=7))).strftime("%d/%m/%Y %H:%M")
        except (ValueError, TypeError):
            return "—"

    @app.after_request
    def response_headers(response):
        response.headers["X-Request-ID"] = g.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; font-src 'self'; connect-src 'self'; "
            "object-src 'none'; base-uri 'self'; frame-ancestors 'self'; form-action 'self'"
        )
        # Trang có CSRF và dữ liệu thử của người dùng không được cache.
        if response.mimetype in ("text/html", "application/json"):
            response.headers["Cache-Control"] = "no-store"
        return response

    return app
