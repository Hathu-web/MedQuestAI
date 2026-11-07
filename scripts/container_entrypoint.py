"""Kiểm tra DB trước khi phục vụ HTTP; không tự migration, seed hoặc gọi AI."""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def preflight():
    sys.path.insert(0, str(ROOT))
    from app import create_app
    from app.extensions import db
    from app.cli import require_schema
    app = create_app()
    with app.app_context():
        engine = db.engine
        try:
            if engine.dialect.name != "sqlite" or engine.url.database in (None, ":memory:"):
                raise ValueError("Bản đóng gói này dùng SQLite trên volume bền vững.")
            path = Path(engine.url.database)
            if not path.is_file() or not path.stat().st_size:
                raise ValueError("Chưa có database. Cài mới: docker compose run --rm web python -m flask --app medquest db upgrade. DB cũ: đọc docs/DOCKER.md trước khi chuyển dữ liệu.")
            require_schema()
        finally:
            # Nhánh schema lỗi cũng phải nhả file SQLite trước khi thoát.
            try:
                db.session.remove()
            finally:
                engine.dispose()


def main():
    command = sys.argv[1:]
    if not command:
        raise SystemExit("Thiếu lệnh khởi động container.")
    if Path(command[0]).name == "gunicorn":
        try:
            preflight()
        except Exception as exc:
            raise SystemExit(f"Chưa khởi động web: {exc}") from exc
    os.execvp(command[0], command)


if __name__ == "__main__":
    main()
