"""Thử nâng DB đã có tài khoản, hội thoại, AI log; kiểm tra toàn bộ hàng cũ."""
from contextlib import closing
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from flask_migrate import upgrade
from sqlalchemy import text

from app import create_app
from app.extensions import db
from app.models import User, CaseVersion, SimulationSession, AIOperation, AICall, Message
from app.services.account_service import create_admin
from app.services.case_service import import_packages, load_package
from scripts.upgrade_step6 import inspect_database
from scripts.upgrade_step3 import backup_before_upgrade

ROOT = Path(__file__).resolve().parents[1]


def snapshot(path):
    with closing(sqlite3.connect(path)) as connection:
        names = [r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
                 if r[0] not in ("alembic_version", "ai_chunks")]
        return {name: connection.execute('SELECT * FROM "' + name.replace('"', '""') + '" ORDER BY 1').fetchall() for name in names}


class UpgradeStep6Tests(unittest.TestCase):
    def test_old_upgrade_entry_also_backs_up_revision_0002(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "database.sqlite"
            with closing(sqlite3.connect(path)) as connection:
                connection.executescript("CREATE TABLE alembic_version (version_num TEXT);"
                    "INSERT INTO alembic_version VALUES ('0002_auth');"
                    "CREATE TABLE users (id INTEGER PRIMARY KEY, auth_version INTEGER);"
                    "INSERT INTO users VALUES (1, 1);")
                connection.commit()
            before = path.read_bytes()
            backup = backup_before_upgrade(path)
            self.assertTrue(backup.is_file())
            self.assertEqual(snapshot(backup), snapshot(path))
            self.assertEqual(path.read_bytes(), before)

    def test_upgrade_preserves_all_old_rows_password_and_valid_backup_and_is_repeatable(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "Thư mục có dấu cách" / "medquest_ai"
            shutil.copytree(ROOT, root, ignore=shutil.ignore_patterns("__pycache__", ".env", "instance", ".venv", "*.pyc"))
            # DB ngoài folder code, giống trường hợp dự án của bạn.
            instance = root.parent / "instance"
            app = create_app("testing", instance_path=str(instance))
            with app.app_context():
                upgrade(directory=str(root / "migrations"), revision="0002_auth")
                admin = create_admin("old@example.com", "Tài khoản cũ", "previous-password-long")
                password_hash = admin.password_hash
                import_packages([load_package(p) for p in sorted((root / "data/cases").glob("*.json"))], admin.email_normalized)
                version = db.session.scalar(db.select(CaseVersion))
                item = SimulationSession(user_id=admin.id, case_version_id=version.id, mode="TEST",
                    start_request_key="old-start", start_input_hash="a" * 64, state_json={"state_id": "S0"})
                db.session.add(item)
                db.session.flush()
                operation = AIOperation(session_id=item.id, request_key="old-turn", input_hash="b" * 64,
                    kind="TURN", status="SUCCEEDED", expected_state_version=0, input_payload_json={"old": True})
                db.session.add(operation)
                db.session.flush()
                db.session.add_all([Message(session_id=item.id, operation_id=operation.id, seq_no=1,
                    sender="PATIENT", content_text="Hội thoại cũ cần giữ nguyên"),
                    AICall(operation_id=operation.id, stage="PATIENT", attempt_no=1, status="SUCCEEDED",
                           actual_cost_microusd=25, usage_json={"total_tokens": 10})])
                db.session.commit()
                database = Path(db.engine.url.database)
                db.session.remove()
                db.engine.dispose()
            before = snapshot(database)
            env_file = root / ".env"
            env_file.write_text("# File cấu hình riêng cần giữ nguyên\n", encoding="utf-8")
            environment = dict(os.environ, MEDQUEST_ENV="development", DEV_DATABASE_URL="sqlite:///" + database.as_posix(),
                SECRET_KEY="isolated-upgrade-test-key-thirty-two-characters", AI_CHAT_ENABLED="false", PYTHONIOENCODING="utf-8")
            for _ in range(2):
                result = subprocess.run([sys.executable, str(root / "scripts/upgrade_step6.py")], cwd=root,
                    env=environment, capture_output=True, text=True, encoding="utf-8", timeout=60)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("OK: revision 0003_rag", result.stdout)
                self.assertEqual(snapshot(database), before)
                self.assertEqual(env_file.read_text(encoding="utf-8"), "# File cấu hình riêng cần giữ nguyên\n")
                backups = list((instance / "backups").glob("*before_step6*.sqlite"))
                self.assertEqual(len(backups), 1)
                self.assertEqual(snapshot(backups[0]), before)
            with closing(sqlite3.connect(backups[0])) as backup:
                self.assertEqual(backup.execute("SELECT version_num FROM alembic_version").fetchone()[0], "0002_auth")
            with app.app_context():
                self.assertEqual(db.session.scalar(text("SELECT version_num FROM alembic_version")), "0003_rag")
                user = db.session.get(User, 1)
                self.assertEqual(user.password_hash, password_hash)
                self.assertTrue(user.check_password("previous-password-long"))
                self.assertEqual(db.session.execute(text("PRAGMA foreign_key_check")).all(), [])
                db.session.add(AICall(operation_id=1, stage="EMBEDDING", attempt_no=1, status="SUCCEEDED"))
                db.session.commit()
                db.session.remove()
                db.engine.dispose()

    def test_missing_empty_and_unversioned_databases_are_not_modified(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "database.sqlite"
            with self.assertRaises(ValueError):
                inspect_database(path)
            self.assertFalse(path.exists())
            path.touch()
            with self.assertRaises(ValueError):
                inspect_database(path)
            self.assertEqual(path.stat().st_size, 0)
            with closing(sqlite3.connect(path)) as connection:
                connection.execute("CREATE TABLE preserve_me (id INTEGER)")
                connection.commit()
            original = path.read_bytes()
            with self.assertRaises((ValueError, sqlite3.Error)):
                inspect_database(path)
            self.assertEqual(path.read_bytes(), original)
            self.assertFalse((path.parent / "backups").exists())


if __name__ == "__main__":
    unittest.main()
