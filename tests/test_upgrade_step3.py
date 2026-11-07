"""Nâng cấp thật trong bản sao dự án, kiểm tra dữ liệu và bản backup trước migration."""
from contextlib import closing
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from flask_migrate import downgrade, upgrade
from sqlalchemy import text

from app import create_app
from app.extensions import db
from app.models import User
from app.services.account_service import create_admin
from app.services.case_service import import_packages, load_package
from scripts.upgrade_step3 import backup_before_upgrade

ROOT = Path(__file__).resolve().parents[1]


class UpgradeStep3TestCase(unittest.TestCase):
    def test_script_preserves_populated_step2_and_keeps_preupgrade_backup(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / "Thư mục có dấu cách" / "medquest_ai"
            shutil.copytree(ROOT, root, ignore=shutil.ignore_patterns("__pycache__", ".env", "instance", ".venv", "*.pyc"))
            instance = root / "instance"
            app = create_app("testing", instance_path=str(instance))
            with app.app_context():
                upgrade(directory=str(root / "migrations"))
                admin = create_admin("admin@medquest.local", "Admin đã có", "existing-admin-password")
                old_hash = admin.password_hash
                import_packages([load_package(p) for p in sorted((root / "data/cases").glob("*.json"))], admin.email_normalized)
                db.session.remove()
                downgrade(directory=str(root / "migrations"), revision="0001_p0")
                database = Path(db.engine.url.database)
                db.engine.dispose()

            def snapshot(path):
                with closing(sqlite3.connect(path)) as connection:
                    tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT IN ('alembic_version','ai_chunks')")]
                    data = {}
                    for table in tables:
                        columns = [row[1] for row in connection.execute(f'PRAGMA table_info("{table}")') if row[1] != "auth_version"]
                        quoted = ",".join('"'+c+'"' for c in columns)
                        data[table] = connection.execute(f'SELECT {quoted} FROM "{table}" ORDER BY 1').fetchall()
                    return data

            before = snapshot(database)
            with app.app_context():
                client = app.test_client()
                response = client.get("/auth/login")
                self.assertEqual(response.status_code, 503)
                self.assertIn("upgrade_step3.py", response.get_data(as_text=True))
                db.session.remove()
                db.engine.dispose()
            environment = dict(os.environ, MEDQUEST_ENV="development", DEV_DATABASE_URL="sqlite:///" + database.as_posix(),
                               SECRET_KEY="isolated-test-key-at-least-thirty-two-characters", PYTHONIOENCODING="utf-8")
            for iteration in range(2):
                result = subprocess.run([sys.executable, str(root / "scripts/upgrade_step3.py")], cwd=root,
                                        env=environment, capture_output=True, text=True, encoding="utf-8", timeout=60)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("Hoàn tất bước 3", result.stdout)
                self.assertEqual(snapshot(database), before)
                backups = list((instance / "backups").glob("*.sqlite"))
                self.assertEqual(len(backups), 1)
                self.assertEqual(snapshot(backups[0]), before)
            with closing(sqlite3.connect(backups[0])) as backup:
                self.assertEqual(backup.execute("SELECT version_num FROM alembic_version").fetchone()[0], "0001_p0")
                self.assertNotIn("auth_version", [c[1] for c in backup.execute("PRAGMA table_info(users)")])
            with app.app_context():
                self.assertEqual(db.session.scalar(text("SELECT version_num FROM alembic_version")), "0003_rag")
                admin = db.session.get(User, 1)
                self.assertEqual(admin.password_hash, old_hash)
                self.assertTrue(admin.check_password("existing-admin-password"))
                self.assertEqual(admin.auth_version, 1)
                self.assertEqual(db.session.execute(text("PRAGMA foreign_key_check")).all(), [])
                db.session.remove()
                db.engine.dispose()

    def test_backup_rejects_missing_or_unversioned_database_without_modifying_it(self):
        with TemporaryDirectory() as temporary:
            database = Path(temporary) / "existing.sqlite"
            with self.assertRaises(ValueError):
                backup_before_upgrade(database)
            self.assertFalse(database.exists())
            with closing(sqlite3.connect(database)) as connection:
                connection.execute("CREATE TABLE preserve_me (id INTEGER)")
                connection.commit()
            before = database.read_bytes()
            with self.assertRaises(ValueError):
                backup_before_upgrade(database)
            self.assertEqual(database.read_bytes(), before)
            self.assertFalse((database.parent / "backups").exists())


if __name__ == "__main__":
    unittest.main()
