"""Lệnh cài bộ ca, luôn sao lưu DB trước thay đổi và không in khóa API."""
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
import sqlite3

import click
from flask import Blueprint

from .ai.errors import AIError
from .ai.vectorstore import index_case, load_index
from .cli import require_schema
from .extensions import db
from .services.account_service import normalize_email
from .services.case_service import import_packages
from .services.catalog_service import (bundle_versions, curriculum_packages, publish_curriculum,
                                      require_admin, require_live_ai)

catalog = Blueprint("catalog", __name__)


@catalog.cli.command("install")
@click.option("--admin-email", required=True, help="Email admin đang có; giữ nguyên mật khẩu.")
def install(admin_email):
    """Sao lưu -> nhập 4 ca -> embedding API -> phát hành học phần. Chạy lại được."""
    from scripts.backup_database import backup_sqlite
    try:
        require_schema()
        email = normalize_email(admin_email)
        require_admin(email)
        packages = curriculum_packages()
        bundle_versions(packages)  # Phát hiện xung đột trước mọi thay đổi.
        embedder = require_live_ai()
        if db.engine.dialect.name != "sqlite" or db.engine.url.database in (None, "", ":memory:"):
            raise ValueError("Bộ cài này cần database SQLite dạng file để sao lưu.")
        source = Path(db.engine.url.database).resolve()
        db.session.rollback()
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_UTC")
        backup = source.parent / "backups" / f"before_four_cases_{stamp}_{uuid4().hex[:8]}.sqlite"
        backup_sqlite(source, backup)
        click.echo(f"Database đang dùng: {source}")
        click.echo(f"Đã sao lưu: {backup}")
        for code, number, message in import_packages(packages, email):
            click.echo(f"{code} v{number}: {message}")
        identifiers = [v.id for v in bundle_versions(packages)]
        for identifier in identifiers:
            from .models import CaseVersion
            version = db.session.get(CaseVersion, identifier)
            try:
                rows = load_index(version, embedder)
                click.echo(f"Chỉ mục vID={identifier}: còn hợp lệ ({len(rows)} đoạn), giữ nguyên.")
                db.session.rollback()
            except AIError:
                db.session.rollback()
                count = index_case(identifier, embedder)
                click.echo(f"Đã index vID={identifier}: {count} đoạn.")
        for identifier, code, number in publish_curriculum(packages, email, embedder):
            click.echo(f"SẴN SÀNG: {code} v{number} | id={identifier} | PUBLISHED · COURSEWORK")
        click.echo("Đã mở 4 ca cho học viên. Tài khoản học viên tạo lượt PRACTICE; admin dùng TEST để kiểm tra ca.")
        click.echo("Lịch sử/điểm cũ giữ nguyên. Phát hành trong đồ án không thay thế thẩm định chuyên môn.")
    except (AIError, ValueError, OSError, sqlite3.Error) as exc:
        db.session.rollback()
        raise click.ClickException(f"{exc}\nNếu dừng ở bước index: sửa lỗi rồi chạy lại cùng lệnh; không xóa database.") from exc
    finally:
        db.session.remove()
        db.engine.dispose()
