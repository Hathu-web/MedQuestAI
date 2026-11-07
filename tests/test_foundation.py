import re
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from sqlalchemy import text

from app import create_app
from app.extensions import db


class FoundationTestCase(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = create_app("testing", instance_path=self.temp.name)
        self.client = self.app.test_client()

    def csrf_headers(self):
        page = self.client.get("/preview/room").get_data(as_text=True)
        token = re.search(r'name="csrf-token" content="([^"]+)"', page).group(1)
        return {"X-CSRFToken": token}

    def test_factories_have_independent_config_and_database_paths(self):
        first = create_app("development", {"SECRET_KEY": "a" * 40},
                           instance_path=str(Path(self.temp.name) / "development"))
        second = create_app("demo", {"SECRET_KEY": "b" * 40},
                            instance_path=str(Path(self.temp.name) / "demo"))
        self.assertNotEqual(first.config["SECRET_KEY"], second.config["SECRET_KEY"])
        with first.app_context():
            first_path = db.engine.url.database
        with second.app_context():
            second_path = db.engine.url.database
        self.assertNotEqual(first_path, second_path)
        self.assertEqual(first.config["ENVIRONMENT"], "development")
        self.assertEqual(second.config["ENVIRONMENT"], "demo")

    def test_factory_does_not_create_database_or_tables(self):
        self.assertEqual(list(Path(self.temp.name).glob("*.sqlite")), [])
        with self.app.app_context():
            self.assertEqual(len(db.metadata.tables), 15)  # Metadata không tự tạo bảng vật lý.

    def test_testing_ignores_real_environment_secrets_and_database(self):
        with patch("app.environment_values", return_value={
            "SECRET_KEY": "real-secret-should-not-appear",
            "DEV_DATABASE_URL": "sqlite:///private.sqlite",
        }):
            test_app = create_app("testing", instance_path=self.temp.name)
        self.assertNotIn("private", test_app.config["SQLALCHEMY_DATABASE_URI"])
        self.assertNotEqual(test_app.config["SECRET_KEY"], "real-secret-should-not-appear")

    def test_invalid_environment_and_missing_demo_secret_fail_early(self):
        with self.assertRaises(ValueError):
            create_app("unknown", instance_path=self.temp.name)
        with patch("app.environment_values", return_value={}):
            with self.assertRaises(ValueError):
                create_app("demo", instance_path=self.temp.name)

    def test_sqlite_foreign_keys_enabled(self):
        with self.app.app_context():
            self.assertEqual(db.session.execute(text("PRAGMA foreign_keys")).scalar_one(), 1)
            db.session.remove()
            db.engine.dispose()

    def test_pages_render_and_assets_are_local(self):
        for path in ("/", "/guide", "/preview/room"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                html = response.get_data(as_text=True)
                self.assertIn("MedQuest", html)
                self.assertNotIn('src="https://', html)
                self.assertNotIn('href="https://', html)
                self.assertIn("no-store", response.headers["Cache-Control"])

    def test_referenced_static_assets_exist(self):
        for path in ("css/app.css", "js/room.js", "images/patient-room.png",
                     "vendor/bootstrap/bootstrap.min.css", "vendor/icons/bootstrap-icons.min.css",
                     "vendor/icons/fonts/bootstrap-icons.woff2"):
            with self.subTest(path=path):
                response = self.client.get("/static/" + path)
                self.assertEqual(response.status_code, 200)
                self.assertGreater(len(response.data), 100)
                response.close()

    def test_health_returns_traceable_json_without_secrets(self):
        response = self.client.get("/api/v1/health")
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["data"]["ai_connected"])
        self.assertEqual(response.headers["X-Request-ID"], payload["request_id"])
        self.assertNotIn("SECRET_KEY", response.get_data(as_text=True))

    def test_preview_requires_csrf(self):
        response = self.client.post("/api/v1/preview/messages", json={"text": "Xin chào"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"]["code"], "CSRF_INVALID")

    def test_preview_returns_only_sample_response_and_matching_fact(self):
        response = self.client.post("/api/v1/preview/messages", headers=self.csrf_headers(),
                                    json={"text": "Anh bắt đầu khó chịu từ khi nào?"})
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()["data"]
        self.assertTrue(payload["preview_only"])
        self.assertEqual(payload["fact"]["key"], "onset")
        self.assertEqual(list(Path(self.temp.name).glob("*.sqlite")), [])

    def test_invalid_preview_inputs_are_rejected(self):
        headers = self.csrf_headers()
        for value in ({"text": " "}, {"text": 7}, {"text": "x" * 2001},
                      {"text": "Xin chào", "role": "admin"}, [], None):
            with self.subTest(value_type=type(value).__name__):
                import json
                response = self.client.post("/api/v1/preview/messages", headers=headers,
                                            data=json.dumps(value), content_type="application/json")
                self.assertEqual(response.status_code, 400)
                self.assertFalse(response.get_json()["ok"])

    def test_oversized_payload_rejected_with_json(self):
        response = self.client.post("/api/v1/preview/messages", headers=self.csrf_headers(),
                                    json={"text": "a" * 20000})
        self.assertEqual(response.status_code, 413)
        self.assertFalse(response.get_json()["ok"])

    def test_errors_follow_html_json_boundaries(self):
        html = self.client.get("/not-a-page")
        api = self.client.get("/api/v1/not-an-endpoint")
        self.assertEqual(html.status_code, 404)
        self.assertEqual(html.mimetype, "text/html")
        self.assertEqual(api.status_code, 404)
        self.assertEqual(api.mimetype, "application/json")
        self.assertEqual(api.get_json()["error"]["code"], "HTTP_404")

    def test_405_keeps_allow_header(self):
        response = self.client.get("/api/v1/preview/messages")
        self.assertEqual(response.status_code, 405)
        self.assertIn("POST", response.headers["Allow"])

    def test_500_does_not_expose_exception(self):
        self.app.config["PROPAGATE_EXCEPTIONS"] = False

        @self.app.get("/api/v1/test-crash")
        def crash():
            raise RuntimeError("private-marker-for-error-test")

        with self.assertLogs(self.app.logger, level="ERROR"):
            response = self.client.get("/api/v1/test-crash")
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.get_json()["error"]["code"], "INTERNAL_ERROR")
        self.assertNotIn("private-marker", response.get_data(as_text=True))

    def test_preview_can_be_disabled_on_both_page_and_api(self):
        headers = self.csrf_headers()
        self.app.config["PREVIEW_ENABLED"] = False
        self.assertEqual(self.client.get("/preview/room").status_code, 404)
        response = self.client.post("/api/v1/preview/messages", headers=headers, json={"text": "Chào"})
        self.assertEqual(response.status_code, 404)

    def test_security_headers_are_present(self):
        response = self.client.get("/")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("script-src 'self'", response.headers["Content-Security-Policy"])
        self.assertNotIn("unsafe-inline", response.headers["Content-Security-Policy"])

    def test_cli_check_and_migration_command_registered(self):
        runner = self.app.test_cli_runner()
        result = runner.invoke(args=["check"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("OK:", result.output)
        result = runner.invoke(args=["db", "--help"])
        self.assertEqual(result.exit_code, 0, result.output)


if __name__ == "__main__":
    unittest.main()
