"""Nâng cấp từ bước 2: sao lưu SQLite trước, giữ nguyên admin, ca và cấu hình."""
from datetime import datetime, timezone
from contextlib import closing
from pathlib import Path
import secrets
import sqlite3
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def backup_before_upgrade(database):
    """Giữ tương thích bước 6: mọi lần nâng từ schema cũ đều có bản sao."""
    database = Path(database).resolve()
    if not database.is_file():
        raise ValueError("Chưa có database. Với cài mới, chạy: python scripts/setup_database.py")
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=10)) as source:
        try:
            revisions = source.execute("SELECT version_num FROM alembic_version").fetchall()
        except sqlite3.DatabaseError as exc:
            raise ValueError("Database chưa có migration hợp lệ. Giữ nguyên tệp và kiểm tra lại bước 2.") from exc
        if revisions in ([("0002_auth",)], [("0003_rag",)]):
            columns = {row[1] for row in source.execute("PRAGMA table_info(users)")}
            if "auth_version" not in columns:
                raise ValueError("Migration và bảng users chưa khớp. Giữ nguyên database để kiểm tra.")
            if revisions == [("0002_auth",)]:
                from scripts.upgrade_step6 import inspect_database
                backup, _counts = inspect_database(database)
                return backup
            return None
        if revisions != [("0001_p0",)]:
            raise ValueError("Lệnh này chỉ nâng từ 0001_p0 lên 0002_auth; database hiện không phù hợp.")
        if source.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise ValueError("SQLite báo lỗi toàn vẹn. Chưa thực hiện nâng cấp.")
        if source.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("Database có liên kết không hợp lệ. Chưa thực hiện nâng cấp.")
        folder = database.parent / "backups"
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_UTC")
        backup = folder / f"{database.stem}_before_step3_{stamp}_{secrets.token_hex(3)}.sqlite"
        with closing(sqlite3.connect(backup)) as destination:
            source.backup(destination)
            if destination.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                raise ValueError("Bản sao chưa vượt kiểm tra toàn vẹn. Chưa nâng cấp database.")
        return backup


def run(*arguments):
    result = subprocess.run([sys.executable, *arguments], cwd=ROOT, check=False)
    if result.returncode:
        raise RuntimeError("Đã dừng tại lệnh lỗi. Giữ nguyên database và bản sao để kiểm tra thông báo phía trên.")


def main():
    print("Hãy dừng Flask bằng Ctrl+C trước khi cập nhật.", flush=True)
    try:
        run(str(ROOT / "scripts/setup_local.py"))
        sys.path.insert(0, str(ROOT))
        from app import create_app
        from app.extensions import db
        app = create_app()
        with app.app_context():
            if db.engine.dialect.name != "sqlite" or db.engine.url.database in (None, ":memory:"):
                raise ValueError("Bản nâng cấp này dành cho database SQLite local của MedQuest.")
            database = Path(db.engine.url.database)
            backup = backup_before_upgrade(database)
            db.engine.dispose()
        if backup:
            print(f"Đã sao lưu: {backup}", flush=True)
        else:
            print("Database đã ở bước 3. Kiểm tra lại, không tạo bản sao lặp.", flush=True)
        run("-m", "flask", "--app", "medquest", "db", "upgrade")
        run("-m", "flask", "--app", "medquest", "check", "--db")
    except (ValueError, RuntimeError, sqlite3.Error, OSError) as exc:
        print(f"\nChưa hoàn tất: {exc}", file=sys.stderr)
        return 1
    print("\nHoàn tất bước 3. Admin và các ca đã có được giữ nguyên.")
    print("Chạy: python -m flask --app medquest run")
    print("Mở http://127.0.0.1:5000/auth/login bằng tài khoản admin đã tạo, hoặc đăng ký học viên.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
