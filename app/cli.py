"""Lệnh local: kiểm tra, tạo admin và nhập ca theo giao dịch."""
from pathlib import Path
import unittest
import click
from flask import current_app
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError
from .extensions import db
from .models import Case, CaseVersion, RubricCriterion, User
from .services.account_service import create_admin, normalize_email
from .services.case_service import import_packages, load_package


def require_schema():
    tables = set(inspect(db.engine).get_table_names())
    missing = set(db.metadata.tables) - tables
    if missing == {"ai_chunks"} and "alembic_version" in tables:
        raise click.ClickException("Database bước 5 cần nâng cấp có sao lưu: python scripts/upgrade_step6.py")
    if missing or "alembic_version" not in tables:
        raise click.ClickException("Database chưa đủ bảng. Chạy: python -m flask --app medquest db upgrade")
    revisions = set(db.session.execute(text("SELECT version_num FROM alembic_version")).scalars())
    if revisions != {current_app.config["DATABASE_REVISION"]}:
        raise click.ClickException("Revision database chưa khớp. Với bản bước 5, chạy scripts/upgrade_step6.py trước khi dùng RAG.")


def read_cases(paths):
    selected = [Path(p) for p in paths] if paths else sorted((Path(current_app.root_path).parent / "data/cases").glob("*.json"))
    if not selected:
        raise click.ClickException("Không tìm thấy tệp ca JSON.")
    try:
        return [load_package(p) for p in selected]
    except (OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc


def register_commands(app):
    @app.cli.command("check")
    @click.option("--db", "check_db", is_flag=True, help="Kiểm tra schema, khóa ngoại và số lượng dữ liệu.")
    def check(check_db):
        root = Path(current_app.static_folder)
        required = ["css/app.css", "js/room.js", "images/patient-room.png", "images/patient-female.png",
                    "images/patient-student.png", "vendor/bootstrap/bootstrap.min.css"]
        missing = [name for name in required if not (root / name).is_file()]
        click.echo(f"MedQuest AI | {current_app.config['BUILD_STAGE']}")
        click.echo(f"Environment: {current_app.config['ENVIRONMENT']}")
        click.echo("Blueprints: " + ", ".join(sorted(current_app.blueprints)))
        click.echo("AI: " + ("RAG đã bật; dùng ai check-provider để kiểm tra provider." if current_app.config.get("AI_CHAT_ENABLED") else "chế độ phản hồi mẫu; RAG chưa bật."))
        click.echo("AI Tutor: " + ("bật; chấm sau khi nộp tổng kết." if current_app.config.get("AI_TUTOR_ENABLED") else "chưa bật."))
        if missing:
            raise click.ClickException("Thiếu tài nguyên: " + ", ".join(missing))
        click.echo(f"Models: {len(db.metadata.tables)} bảng nghiệp vụ/chỉ mục; schema quản lý bằng migration.")
        if check_db:
            require_schema()
            if db.engine.dialect.name == "sqlite":
                if db.session.execute(text("PRAGMA foreign_keys")).scalar_one() != 1:
                    raise click.ClickException("Kiểm tra khóa ngoại SQLite chưa được bật.")
                if db.session.execute(text("PRAGMA foreign_key_check")).first():
                    raise click.ClickException("Database có liên kết khóa ngoại không hợp lệ.")
            for model in (User, Case, CaseVersion, RubricCriterion):
                count = db.session.scalar(db.select(db.func.count()).select_from(model))
                click.echo(f"{model.__tablename__}: {count}")
        click.echo("OK: cấu hình và tài nguyên đã sẵn sàng." if not check_db else "OK: database và tài nguyên hợp lệ.")

    @app.cli.command("create-admin")
    @click.option("--email", required=True, help="Email quản trị; nhập mật khẩu ở lời nhắc ẩn.")
    @click.option("--name", default="Quản trị MedQuest", show_default=True)
    def admin_command(email, name):
        require_schema()
        try:
            email = normalize_email(email)
            existing = db.session.scalar(db.select(User).where(User.email_normalized == email))
            if existing:
                if existing.role == "ADMIN" and existing.is_active:
                    click.echo("Admin đã tồn tại; giữ nguyên mật khẩu và quyền hiện tại.")
                    return
                raise ValueError("Email đã dùng hoặc tài khoản bị khóa; không tự nâng quyền/mở khóa.")
            password = click.prompt("Mật khẩu mới (12–128 ký tự)", hide_input=True, confirmation_prompt="Nhập lại mật khẩu")
            create_admin(email, name, password)
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
        except SQLAlchemyError as exc:
            db.session.rollback()
            raise click.ClickException("Không thể tạo admin do xung đột database; chưa lưu thay đổi.") from exc
        click.echo("Đã tạo admin ACTIVE, gắn nhãn kiểm thử. Mật khẩu chỉ lưu dạng băm.")
        click.echo("Đăng nhập bằng tài khoản vừa tạo tại /auth/login.")

    @app.cli.command("validate-cases")
    @click.argument("paths", nargs=-1, type=click.Path(exists=True, dir_okay=False))
    def validate_command(paths):
        for package in read_cases(paths):
            click.echo(f"OK: {package['case_code']} v{package['version_no']} · {len(package['content']['facts'])} dữ kiện · {len(package['rubric'])} tiêu chí · 100 điểm")
        click.echo("Kiểm tra cấu trúc thành công; không thay thế rà soát đào tạo/chuyên môn.")

    @app.cli.command("import-cases")
    @click.option("--admin-email", required=True)
    @click.argument("paths", nargs=-1, type=click.Path(exists=True, dir_okay=False))
    def import_command(admin_email, paths):
        packages = read_cases(paths)
        require_schema()
        try:
            result = import_packages(packages, normalize_email(admin_email))
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
        except SQLAlchemyError as exc:
            db.session.rollback()
            raise click.ClickException("Nhập thất bại do xung đột database; đã rollback toàn bộ lô.") from exc
        for code, version, message in result:
            click.echo(f"{code} v{version}: {message}")

    @app.cli.command("list-cases")
    def list_command():
        require_schema()
        versions = db.session.scalars(db.select(CaseVersion).join(Case).order_by(Case.case_code, CaseVersion.version_no)).all()
        if not versions:
            click.echo("Chưa nhập ca. Dùng lệnh import-cases sau khi tạo admin.")
        for version in versions:
            click.echo(f"{version.case.case_code} v{version.version_no} | {version.status} | demo_only={version.demo_only} | {version.title}")

    @app.cli.command("test")
    def test():
        root = Path(current_app.root_path).parent
        suite = unittest.defaultTestLoader.discover(str(root / "tests"), top_level_dir=str(root))
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        if not result.wasSuccessful():
            raise click.ClickException("Kiểm thử chưa đạt.")
