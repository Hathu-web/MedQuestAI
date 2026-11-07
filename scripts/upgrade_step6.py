"""Nâng đúng SQLite đang cấu hình: sao lưu trước khi chuyển 0002_auth -> 0003_rag."""
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import secrets
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]


def inspect_database(database):
    database = Path(database).resolve()
    if not database.is_file() or database.stat().st_size == 0:
        raise ValueError("Không tìm thấy DB có dữ liệu. Kiểm tra DEV_DATABASE_URL; không tạo DB mới.")
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=10)) as source:
        if source.execute("PRAGMA integrity_check").fetchone() != ("ok",) or source.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("Database chưa đạt kiểm tra toàn vẹn; chưa nâng cấp.")
        revisions = source.execute("SELECT version_num FROM alembic_version").fetchall()
        if revisions not in ([("0002_auth",)], [("0003_rag",)]):
            raise ValueError("Cần database bước 5 ở revision 0002_auth, hoặc bản đã nâng 0003_rag.")
        tables = [r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
                  if r[0] not in ("ai_chunks", "alembic_version")]
        # Tên bảng đọc từ SQLite; quote kép để không ghép SQL không được escape.
        counts = {name: source.execute('SELECT COUNT(*) FROM "' + name.replace('"', '""') + '"').fetchone()[0]
                  for name in tables}
        if revisions == [("0003_rag",)]:
            return None, counts
        folder = database.parent / "backups"
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_UTC")
        backup = folder / f"{database.stem}_before_step6_{stamp}_{secrets.token_hex(3)}.sqlite"
        with closing(sqlite3.connect(backup)) as target:
            source.backup(target)
            if target.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                raise ValueError("Bản sao chưa hợp lệ; chưa nâng cấp.")
        return backup, counts


def main():
    sys.path.insert(0, str(ROOT))
    from app import create_app
    from app.extensions import db
    from app.cli import require_schema
    from flask_migrate import upgrade
    print("Dừng server Flask trước khi chạy lệnh nâng cấp này.", flush=True)
    try:
        app = create_app()
        with app.app_context():
            if db.engine.dialect.name != "sqlite" or db.engine.url.database in (None, ":memory:"):
                raise ValueError("Script này dành cho SQLite local.")
            database = Path(db.engine.url.database).resolve()
            print(f"DATABASE: {database}", flush=True)
            backup, before = inspect_database(database)
            if backup:
                print(f"BACKUP: {backup}", flush=True)
                upgrade(directory=str(ROOT / "migrations"), revision="0003_rag")
            require_schema()
            db.session.remove()
            _unused, after = inspect_database(database)
            if before != after:
                raise ValueError("Số bản ghi cũ không khớp. Giữ bản sao và dừng để kiểm tra.")
            db.engine.dispose()
        print("OK: revision 0003_rag; dữ liệu cũ được giữ nguyên. Chưa gọi dịch vụ AI.")
        return 0
    except Exception as exc:
        print(f"Chưa hoàn tất: {exc}", file=sys.stderr)
        print("Giữ nguyên database và file backup đã in; không chạy reset/stamp/downgrade.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
