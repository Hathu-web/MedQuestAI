"""Cấu hình triển khai và DB preflight; không cần Docker hoặc API key thật."""
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
import unittest
from unittest.mock import patch

from click import ClickException
from sqlalchemy import event

from app import create_app
from app.extensions import db
from scripts.container_entrypoint import preflight


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.values = {"MEDQUEST_ENV": "production", "SECRET_KEY": "test-only-" + "x" * 40,
            "MEDQUEST_INSTANCE_PATH": str(self.root),
            "DATABASE_URL": "sqlite:///persistent.sqlite"}

    def make_app(self):
        with patch("app.environment_values", return_value=self.values):
            app = create_app()
        def cleanup():
            with app.app_context():
                db.session.remove()
                db.engine.dispose()
        self.addCleanup(cleanup)
        return app

    def test_production_requires_a_stable_secret_before_opening_database(self):
        for secret in ("", "short"):
            self.values["SECRET_KEY"] = secret
            with self.subTest(secret=secret), patch("app.environment_values", return_value=self.values):
                with self.assertRaises(ValueError):
                    create_app()
        self.assertFalse((self.root / "persistent.sqlite").exists())

    def test_production_path_cookie_host_and_preview_defaults(self):
        app = self.make_app()
        self.assertEqual(app.instance_path, str(self.root))
        self.assertTrue(app.config["SESSION_COOKIE_SECURE"])
        self.assertFalse(app.config["DEBUG"])
        self.assertFalse((self.root / "persistent.sqlite").exists())
        initialized = app.test_cli_runner().invoke(args=["db", "upgrade"])
        self.assertEqual(initialized.exit_code, 0, initialized.output)
        client = app.test_client()
        self.assertEqual(client.get("/api/v1/health").status_code, 200)
        self.assertEqual(client.get("/preview/room").status_code, 404)
        for path in ("/", "/guide", "/auth/login"):
            response = client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertNotIn("/preview/room", response.get_data(as_text=True))
        self.assertEqual(client.get("/api/v1/health", base_url="http://untrusted.invalid").status_code, 400)

    def test_local_http_opt_in_and_invalid_cookie_or_host_config(self):
        self.values.update(SESSION_COOKIE_SECURE="false", TRUSTED_HOSTS="localhost,127.0.0.1")
        self.assertFalse(self.make_app().config["SESSION_COOKIE_SECURE"])
        for values in ({"SESSION_COOKIE_SECURE": "maybe"}, {"TRUSTED_HOSTS": " , "}):
            with patch("app.environment_values", return_value={**self.values, **values}):
                with self.assertRaises(ValueError):
                    create_app()

    def test_testing_does_not_read_production_database_key_or_ai_flags(self):
        self.values.update(LLM_API_KEY="private-marker", AI_TUTOR_ENABLED="true")
        with patch("app.environment_values", return_value=self.values):
            app = create_app("testing", instance_path=str(self.root / "isolated-test"))
        self.assertNotEqual(app.config["SECRET_KEY"], self.values["SECRET_KEY"])
        self.assertNotIn("persistent", app.config["SQLALCHEMY_DATABASE_URI"])
        self.assertEqual(app.config["LLM_API_KEY"], "")
        self.assertFalse(app.config["AI_TUTOR_ENABLED"])
        self.assertFalse((self.root / "persistent.sqlite").exists())

    def test_preflight_missing_database_fails_without_creating_one(self):
        with patch("app.environment_values", return_value=self.values):
            with self.assertRaisesRegex(ValueError, "Chưa có database"):
                preflight()
        self.assertFalse((self.root / "persistent.sqlite").exists())

    def test_preflight_accepts_migrated_database_and_keeps_revision(self):
        app = self.make_app()
        result = app.test_cli_runner().invoke(args=["db", "upgrade"])
        self.assertEqual(result.exit_code, 0, result.output)
        before = (self.root / "persistent.sqlite").read_bytes()
        with patch("app.environment_values", return_value=self.values):
            preflight()
        self.assertEqual((self.root / "persistent.sqlite").read_bytes(), before)

    def test_preflight_rejects_a_database_with_missing_schema(self):
        with closing(sqlite3.connect(self.root / "persistent.sqlite")) as connection:
            connection.execute("CREATE TABLE untouched (value TEXT)")
            connection.commit()
        # Context manager của sqlite3 chỉ quản lý transaction; closing mới đóng file.
        with self.assertRaises(sqlite3.ProgrammingError):
            connection.execute("SELECT 1")

        app = self.make_app()
        opened = []
        with app.app_context():
            engine = db.engine
        event.listen(engine, "connect", lambda connection, _record: opened.append(connection))
        with patch("app.create_app", return_value=app):
            with self.assertRaisesRegex(ClickException, "Database chưa đủ bảng"):
                preflight()
        # Kiểm tra connection thật đã đóng, kể cả Linux cho phép unlink file còn mở.
        self.assertTrue(opened, "Preflight phải mở DB để phát hiện schema thiếu.")
        for connection in opened:
            with self.assertRaises(sqlite3.ProgrammingError):
                connection.execute("SELECT 1")


if __name__ == "__main__":
    unittest.main()
