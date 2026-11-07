"""Kiểm thử luồng HTTP thật với CSRF, nhiều cookie và quyền theo chủ sở hữu."""
import re
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from flask_migrate import upgrade
from sqlalchemy import text
from werkzeug.security import generate_password_hash

from app import create_app
from app.extensions import db
from app.models import AuditLog, CaseVersion, Message, SimulationSession, User
from app.security import safe_next_url
from app.services.account_service import change_password, register_student, set_student_status
from app.services.auth_limiter import AuthLimiter
from app.services.case_service import import_packages, load_package

ROOT = Path(__file__).resolve().parents[1]
PASSWORD = "test-only-long-password"
NEW_PASSWORD = "different-test-password"


class AuthTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.password_hash = generate_password_hash(PASSWORD, method="scrypt")

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.app = create_app("testing", {"AUTH_RATE_LIMIT_ENABLED": False}, instance_path=self.temp.name)
        self.addCleanup(self.cleanup)
        with self.app.app_context():
            upgrade(directory=str(ROOT / "migrations"))
            for email, role, flag in [("admin@medquest.local", "ADMIN", 1),
                                      ("student@example.com", "STUDENT", 0),
                                      ("other@example.com", "STUDENT", 0),
                                      ("admin2@example.com", "ADMIN", 1),
                                      ("tester@example.com", "STUDENT", 1)]:
                db.session.add(User(email_normalized=email, display_name="Người dùng thử", role=role,
                                    is_test_account=flag, password_hash=self.password_hash))
            db.session.commit()
        self.client = self.app.test_client()

    def cleanup(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        self.temp.cleanup()

    def token(self, client=None, path="/auth/login"):
        response = (client or self.client).get(path)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return re.search(r'<meta name="csrf-token" content="([^"]+)"', response.get_data(as_text=True))[1]

    def login(self, client=None, email="student@example.com", password=PASSWORD, next_url=""):
        client = client or self.client
        return client.post("/auth/login", data={"email":email, "password":password, "next":next_url,
                                               "csrf_token":self.token(client)})

    def register(self, **changes):
        data = {"display_name":"Hà Thu", "email":"new@example.com", "password":PASSWORD,
                "password_confirm":PASSWORD, "csrf_token":self.token(path="/auth/register")}
        data.update(changes)
        return self.client.post("/auth/register", data=data)

    def set_status(self, desired="LOCKED", target=2, expected="ACTIVE"):
        with self.app.app_context():
            set_student_status(1, db.session.get(User, 1).auth_version, target, desired, expected)

    def seed_sessions(self):
        with self.app.app_context():
            import_packages([load_package(ROOT / "data/cases/mq_com_01_v1.json")], "admin@medquest.local")
            version = db.session.scalar(db.select(CaseVersion))
            ids = []
            for owner, mode in [(2,"PRACTICE"), (3,"PRACTICE"), (1,"TEST"),
                                (1,"PRACTICE"), (2,"TEST"), (5,"TEST")]:
                item = SimulationSession(user_id=owner, case_version_id=version.id, mode=mode,
                    state_json={"hidden_secret":"NEVER_EXPOSE_STATE", "state_id":"S0"},
                    start_request_key=f"fixture-{owner}-{mode}", start_input_hash="a"*64)
                db.session.add(item)
                db.session.flush()
                ids.append(item.id)
                db.session.add(Message(session_id=item.id, seq_no=1, sender="PATIENT",
                                       content_text='<script>alert("xss")</script> Nội dung đã lưu'))
            db.session.commit()
            return ids

    def test_registration_normalizes_email_hashes_password_and_never_assigns_admin(self):
        response = self.register(email="  NEW@Example.COM  ", role="ADMIN", is_test_account="1", status="LOCKED")
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            user = db.session.scalar(db.select(User).where(User.email_normalized == "new@example.com"))
            self.assertEqual((user.role, user.status, user.is_test_account), ("STUDENT", "ACTIVE", 0))
            self.assertTrue(user.check_password(PASSWORD))
            self.assertNotEqual(user.password_hash, PASSWORD)
            self.assertEqual(db.session.scalar(db.select(AuditLog).where(AuditLog.action == "STUDENT_REGISTERED")).actor_user_id, user.id)
        self.assertEqual(self.client.get("/api/v1/me").status_code, 401)

    def test_duplicate_registration_rolls_back_user_and_audit(self):
        self.assertEqual(self.register().status_code, 302)
        self.assertEqual(self.register(email="NEW@example.com").status_code, 400)
        with self.app.app_context():
            self.assertEqual(db.session.scalar(db.select(db.func.count()).select_from(User)), 6)
            self.assertEqual(db.session.scalar(db.select(db.func.count()).select_from(AuditLog)), 1)

    def test_registration_validation_blocks_invalid_inputs(self):
        for data in [{"email":"not-an-email"}, {"email":"a@localhost"}, {"display_name":"  "},
                     {"password":"short", "password_confirm":"short"},
                     {"password":" "*12, "password_confirm":" "*12}, {"password_confirm":"mismatch"}]:
            with self.subTest(data=data):
                self.assertEqual(self.register(**data).status_code, 400)
        with self.app.app_context():
            self.assertEqual(db.session.scalar(db.select(db.func.count()).select_from(User)), 5)

    def test_registration_audit_failure_is_atomic(self):
        with self.app.app_context():
            with patch.object(db.session, "commit", side_effect=RuntimeError("fixture failure")):
                with self.assertRaises(RuntimeError):
                    register_student("new@example.com", "Tên", PASSWORD)
            self.assertIsNone(db.session.scalar(db.select(User).where(User.email_normalized == "new@example.com")))

    def test_login_local_admin_and_student_and_cookie_fields(self):
        response = self.login(email="ADMIN@medquest.local")
        self.assertEqual(response.location, "/account")
        cookie = response.headers["Set-Cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Lax", cookie)
        with self.client.session_transaction() as session:
            self.assertEqual(session["_user_id"], "1:1")
            self.assertNotIn("password", session)
        self.assertEqual(self.client.get("/admin/users").status_code, 200)
        info = self.client.get("/api/v1/me").get_json()
        self.assertEqual(info["data"]["role"], "ADMIN")
        self.assertNotIn("password", str(info))
        self.assertNotIn("auth_version", str(info))

    def test_bad_credentials_and_locked_login_share_message(self):
        responses = [self.login(email="missing@example.com"), self.login(password="wrong-password")]
        self.set_status()
        responses.append(self.login())
        message = "Email hoặc mật khẩu không đúng, hoặc tài khoản chưa thể đăng nhập."
        for response in responses:
            self.assertEqual(response.status_code, 401)
            self.assertIn(message, response.get_data(as_text=True))

    def test_safe_next_rejects_external_encoded_and_control_urls(self):
        for value in ["https://example.com", "//example.com", "/\\example.com", "/%5cexample.com",
                      "/%2fexample.com", "/%252fexample.com", "/%0d%0aLocation:x", " /account",
                      "/auth/login", "javascript:alert(1)", "/%252525252fexample.com", None]:
            with self.subTest(value=value):
                self.assertIsNone(safe_next_url(value))
        self.assertEqual(safe_next_url("/account?tab=recent"), "/account?tab=recent")
        self.assertEqual(self.login(next_url="//example.com").location, "/account")
        client = self.app.test_client()
        self.assertEqual(self.login(client, next_url="/guide").location, "/guide")

    def test_csrf_required_login_registration_password_and_logout(self):
        for endpoint in ["login", "register"]:
            self.assertEqual(self.client.post(f"/auth/{endpoint}", data={"email":"student@example.com", "password":PASSWORD}).status_code, 400)
        self.login()
        for endpoint in ["password", "logout"]:
            self.assertEqual(self.client.post(f"/auth/{endpoint}", data={}).status_code, 400)
        self.assertEqual(self.client.get("/api/v1/me").status_code, 200)

    def test_logout_requires_post_and_clears_login(self):
        self.login()
        self.assertEqual(self.client.get("/auth/logout").status_code, 405)
        token = self.token(path="/account")
        self.assertEqual(self.client.post("/auth/logout", data={"csrf_token":token}).status_code, 302)
        self.assertEqual(self.client.get("/api/v1/me").status_code, 401)

    def test_password_change_keeps_current_browser_and_revokes_other_browser(self):
        other = self.app.test_client()
        self.login()
        self.login(other)
        token = self.token(path="/auth/password")
        response = self.client.post("/auth/password", data={"current_password":PASSWORD, "password":NEW_PASSWORD,
                                      "password_confirm":NEW_PASSWORD, "csrf_token":token})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get("/api/v1/me").status_code, 200)
        self.assertEqual(other.get("/api/v1/me").status_code, 401)
        self.assertEqual(self.login(other).status_code, 401)
        self.assertEqual(self.login(other, password=NEW_PASSWORD).status_code, 302)
        with self.app.app_context():
            self.assertEqual(db.session.get(User, 2).auth_version, 2)
            audit = db.session.scalar(db.select(AuditLog).where(AuditLog.action == "PASSWORD_CHANGED"))
            self.assertEqual(audit.metadata_json, {"sessions_revoked":True})

    def test_password_wrong_current_or_same_password_keeps_credentials(self):
        self.login()
        for current, new in [("wrong-current",NEW_PASSWORD), (PASSWORD,PASSWORD)]:
            response = self.client.post("/auth/password", data={"current_password":current, "password":new,
                "password_confirm":new, "csrf_token":self.token(path="/auth/password")})
            self.assertEqual(response.status_code, 400)
        with self.app.app_context():
            self.assertTrue(db.session.get(User, 2).check_password(PASSWORD))
            self.assertEqual(db.session.get(User, 2).auth_version, 1)

    def test_stale_version_cannot_change_password(self):
        with self.app.app_context():
            change_password(2, 1, PASSWORD, NEW_PASSWORD)
            with self.assertRaises(ValueError):
                change_password(2, 1, NEW_PASSWORD, "another-new-password")
            self.assertTrue(db.session.get(User, 2).check_password(NEW_PASSWORD))

    def test_locked_session_rejected_on_next_get_and_post_before_csrf(self):
        second = self.app.test_client()
        self.login()
        self.login(second)
        token = self.token(second, path="/account")
        self.set_status()
        self.assertEqual(self.client.get("/account").location, "/auth/login")
        response = second.post("/api/v1/preview/messages", json={"text":"Xin chào"}, headers={"X-CSRFToken":token})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["error"]["code"], "AUTH_REQUIRED")

    def test_unlock_does_not_revive_untouched_old_cookie(self):
        self.login()
        self.set_status()
        self.set_status("ACTIVE", expected="LOCKED")
        self.assertEqual(self.client.get("/api/v1/me").status_code, 401)
        self.assertEqual(self.login().status_code, 302)

    def test_admin_access_and_status_csrf_confirmation_and_conflict(self):
        self.assertEqual(self.client.get("/admin/users").status_code, 302)
        self.login()
        self.assertEqual(self.client.get("/admin/users").status_code, 404)
        admin = self.app.test_client()
        self.login(admin, email="admin@medquest.local")
        path = "/admin/users/2/status"
        token = self.token(admin, path + "?status=LOCKED")
        with self.app.app_context():
            self.assertEqual(db.session.get(User, 2).status, "ACTIVE")
        data = {"status":"LOCKED", "expected_status":"ACTIVE"}
        self.assertEqual(admin.post(path, data=data).status_code, 400)
        data["csrf_token"] = token
        self.assertEqual(admin.post(path, data=data).status_code, 302)
        self.assertEqual(admin.post(path, data=data).status_code, 409)
        with self.app.app_context():
            self.assertEqual(db.session.get(User, 2).status, "LOCKED")
            self.assertEqual(db.session.scalar(db.select(db.func.count()).select_from(AuditLog)), 1)
        for target in [1,4,999]:
            self.assertEqual(admin.get(f"/admin/users/{target}/status?status=LOCKED").status_code, 404)
            self.assertEqual(admin.post(f"/admin/users/{target}/status", data=data).status_code, 404)

    def test_status_service_rejects_student_or_revoked_admin(self):
        with self.app.app_context():
            for actor, version in [(2,1),(1,0)]:
                with self.assertRaises(PermissionError):
                    set_student_status(actor, version, 3, "LOCKED", "ACTIVE")
            self.assertEqual(db.session.get(User, 3).status, "ACTIVE")

    def test_owner_is_enforced_on_html_and_api_even_for_admin(self):
        mine, theirs, admin_test, admin_practice, student_test, tester_test = self.seed_sessions()
        self.assertEqual(self.client.get(f"/api/v1/sessions/{mine}/state").status_code, 401)
        self.login()
        for identifier in [theirs,admin_test,student_test,99999]:
            self.assertEqual(self.client.get(f"/sessions/{identifier}").status_code, 404)
            self.assertEqual(self.client.get(f"/api/v1/sessions/{identifier}/state").status_code, 404)
        self.assertEqual(self.client.get(f"/sessions/{mine}").status_code, 200)
        admin = self.app.test_client()
        self.login(admin, email="admin@medquest.local")
        for identifier in [mine,theirs,admin_practice,tester_test]:
            self.assertEqual(admin.get(f"/sessions/{identifier}").status_code, 404)
            self.assertEqual(admin.get(f"/api/v1/sessions/{identifier}/state").status_code, 404)
        self.assertEqual(admin.get(f"/sessions/{admin_test}").status_code, 200)
        tester = self.app.test_client()
        self.login(tester, email="tester@example.com")
        self.assertEqual(tester.get(f"/sessions/{tester_test}").status_code, 200)

    def test_own_session_projection_hides_private_case_and_escapes_chat(self):
        mine, *_ = self.seed_sessions()
        self.login()
        response = self.client.get(f"/api/v1/sessions/{mine}/state")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()["data"]
        self.assertEqual(set(data), {"id", "status", "mode", "state_version", "turn_index",
            "started_at", "ended_at", "case", "messages", "provider", "max_turns", "can_send",
            "facts", "actions", "summary"})
        for secret in ["NEVER_EXPOSE_STATE", "rubric", "initial_state", "input_payload_json", "password_hash"]:
            self.assertNotIn(secret, response.get_data(as_text=True))
        self.assertEqual(data["facts"], [])  # Fixture chưa mở dữ kiện nào.
        self.assertNotIn("facts", data["case"])
        self.assertIn("patient-student.png", data["case"]["patient"]["image_url"])
        html = self.client.get(f"/sessions/{mine}").get_data(as_text=True)
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn('<script>alert("xss")</script>', html)
        account = self.client.get("/account").get_data(as_text=True)
        self.assertIn(f'href="/sessions/{mine}"', account)
        self.assertNotIn('href="/sessions/2"', account)

    def test_unauthenticated_api_is_json_with_request_id(self):
        response = self.client.get("/api/v1/me")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.mimetype, "application/json")
        self.assertEqual(response.get_json()["request_id"], response.headers["X-Request-ID"])
        self.assertEqual(self.client.get("/account").location, "/auth/login?next=/account")

    def test_rate_limit_keeps_retry_after_and_ignores_forwarded_ip(self):
        self.app.config.update(AUTH_RATE_LIMIT_ENABLED=True, AUTH_LOGIN_LIMIT=2)
        token = self.token()
        for ip in ["1.1.1.1", "2.2.2.2"]:
            response = self.client.post("/auth/login", data={"csrf_token":token, "email":"student@example.com", "password":"wrong"}, headers={"X-Forwarded-For":ip})
            self.assertEqual(response.status_code, 401)
        response = self.client.post("/auth/login", data={"csrf_token":token, "email":"student@example.com", "password":PASSWORD}, headers={"X-Forwarded-For":"3.3.3.3"})
        self.assertEqual(response.status_code, 429)
        self.assertGreater(int(response.headers["Retry-After"]), 0)
        fresh_app = create_app("testing", instance_path=self.temp.name)
        self.assertEqual(len(fresh_app.extensions["auth_limiter"].windows), 0)

    def test_missing_auth_schema_returns_useful_503_without_recursive_error(self):
        with TemporaryDirectory() as temporary:
            app = create_app("testing", instance_path=temporary)
            client = app.test_client()
            with client.session_transaction() as session:
                session["_user_id"] = "1:1"
                session["_permanent"] = True
            response = client.get("/auth/login")
            self.assertEqual(response.status_code, 503)
            self.assertIn("setup_database.py", response.get_data(as_text=True))
            with app.app_context():
                db.engine.dispose()


class LimiterTestCase(unittest.TestCase):
    def test_expiry_and_memory_bound(self):
        limiter = AuthLimiter(max_keys=2)
        with patch("app.services.auth_limiter.time.monotonic", return_value=100):
            self.assertEqual(limiter.consume("a", 1, 60), 0)
            self.assertEqual(limiter.consume("a", 1, 60), 60)
        with patch("app.services.auth_limiter.time.monotonic", return_value=161):
            self.assertEqual(limiter.consume("a", 1, 60), 0)
            limiter.consume("b", 1, 60)
            limiter.consume("c", 1, 60)
            self.assertEqual(len(limiter.windows), 2)


if __name__ == "__main__":
    unittest.main()
