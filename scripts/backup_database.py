"""Sao lưu SQLite đang được app cấu hình, không ghi đè bản sao hoặc sửa DB nguồn."""
import argparse
from contextlib import closing
from pathlib import Path
import sqlite3
import sys


def backup_sqlite(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if not source.is_file() or not source.stat().st_size:
        raise ValueError("Database nguồn chưa tồn tại hoặc đang rỗng; kiểm tra cấu hình đang dùng.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive create: giữ nguyên bản sao nếu đường dẫn đích đã có.
    with destination.open("xb"):
        pass
    try:
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as original:
            with closing(sqlite3.connect(destination)) as copied:
                original.backup(copied)
                if copied.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                    raise ValueError("Bản sao chưa vượt kiểm tra toàn vẹn.")
                copied.commit()
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return destination


def main():
    parser = argparse.ArgumentParser(description="Tạo bản sao nhất quán của DB hiện tại bằng SQLite backup API.")
    parser.add_argument("--output", required=True, help="File mới; không ghi đè nếu đã tồn tại.")
    args = parser.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app import create_app
    from app.extensions import db
    app = create_app()
    try:
        with app.app_context():
            if db.engine.dialect.name != "sqlite" or db.engine.url.database in (None, ":memory:"):
                raise ValueError("Script này chỉ sao lưu database SQLite dạng file.")
            source = Path(db.engine.url.database)
            result = backup_sqlite(source, args.output)
            db.engine.dispose()
        print(f"Nguồn: {source}")
        print(f"Đã sao lưu: {result}")
        return 0
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(f"Chưa sao lưu: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
