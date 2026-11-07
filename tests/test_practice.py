"""Luồng bước 4, quyền truy cập, idempotency, quota đồng thời và điểm thật."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
import re
import unittest
from unittest.mock import patch
from uuid import uuid4

from flask_migrate import upgrade
from werkzeug.security import generate_password_hash

from app import create_app
from app.extensions import db
from app.models import AuditLog, Case, CaseVersion, Evaluation, Message, SimulationSession, Submission, User
from app.models.common import utc_now
from app.services.case_service import import_packages, load_package
from app.services.practice_service import PracticeError, dashboard_data, day_window, start_session

ROOT = Path(__file__).resolve().parents[1]
PASSWORD = "test-fixture-password"


class HiddenInputs(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.values = {}
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        fields = dict(attrs)
        if tag == "input" and fields.get("type") == "hidden" and "name" in fields:
            self.values[fields["name"]] = fields.get("value", "")


class PracticeTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.password_hash = generate_password_hash(PASSWORD, method="scrypt")

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.app = create_app("testing", {"AUTH_RATE_LIMIT_ENABLED":False}, instance_path=self.temp.name)
        self.addCleanup(self.cleanup)
        with self.app.app_context():
            upgrade(directory=str(ROOT / "migrations"))
            for name, role, flag in [("admin","ADMIN",1),("student","STUDENT",0),
                                     ("other","STUDENT",0),("tester","STUDENT",1)]:
                db.session.add(User(email_normalized=f"{name}@example.com", display_name=name,
                    role=role, is_test_account=flag, password_hash=self.password_hash))
            db.session.commit()
            packages = [load_package(p) for p in sorted((ROOT / "data/cases").glob("*.json"))]
            import_packages(packages, "admin@example.com")
            versions = db.session.scalars(db.select(CaseVersion).order_by(CaseVersion.id)).all()
            self.male_id, self.female_id = [v.id for v in versions]
            # Ca PUBLISHED chỉ là fixture trong DB tạm, không phát hành ca trên máy người dùng.
            case = Case(case_code="FIXTURE_PUBLISHED", created_by_id=1)
            db.session.add(case)
            db.session.flush()
            content = deepcopy(versions[0].content_json)
            content["facts"][1]["value"] = "PRIVATE_FACT_NEVER_EXPOSE"
            published = CaseVersion(case_id=case.id, version_no=1, created_by_id=1,
                status="PUBLISHED", title="Ca đã phát hành (fixture)", demo_only=0,
                content_json=content, review_json={"fixture":True}, content_hash="b"*64)
            db.session.add(published)
            db.session.commit()
            self.published_id = published.id
        self.client = self.app.test_client()

    def cleanup(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        self.temp.cleanup()

    def csrf(self, client, path="/"):
        response = client.get(path)
        self.assertEqual(response.status_code, 200)
        return re.search(r'<meta name="csrf-token" content="([^"]+)"', response.get_data(as_text=True))[1]

    def login(self, name="admin", client=None):
        client = client or self.client
        response = client.post("/auth/login", data={"email":f"{name}@example.com", "password":PASSWORD,
            "csrf_token":self.csrf(client, "/auth/login")})
        self.assertEqual(response.status_code, 302)
        return client

    def start(self, version=None, mode="TEST", key=None, client=None):
        client = client or self.client
        return client.post("/api/v1/sessions", json={"case_version_id":version or self.female_id,
            "mode":mode, "request_key":key or uuid4().hex}, headers={"X-CSRFToken":self.csrf(client)})

    def count(self, model):
        return db.session.scalar(db.select(db.func.count()).select_from(model))

    def fixture_session(self, user=2, mode="PRACTICE", status="ACTIVE", assisted=0):
        row = SimulationSession(user_id=user, case_version_id=self.published_id, mode=mode, status=status,
            state_json={"state_id":"S0"}, start_request_key=uuid4().hex, start_input_hash="c"*64,
            assisted=assisted, ended_at=utc_now() if status != "ACTIVE" else None)
        db.session.add(row)
        db.session.flush()
        if status == "COMPLETED":
            db.session.add(Submission(session_id=row.id, summary_json={}, payload_hash="d"*64))
            db.session.flush()
        return row

    def test_guest_redirect_and_unauthenticated_api(self):
        for path in ["/cases", f"/cases/{self.male_id}", "/dashboard"]:
            self.assertEqual(self.client.get(path).status_code, 302)
        self.assertEqual(self.start().status_code, 401)

    def test_student_only_sees_published_and_cannot_forge_test_mode(self):
        self.login("student")
        html = self.client.get("/cases").get_data(as_text=True)
        self.assertIn("Ca đã phát hành (fixture)", html)
        self.assertNotIn("Trần Ngọc Linh", html)
        self.assertEqual(self.client.get(f"/cases/{self.female_id}").status_code, 404)
        self.assertEqual(self.start().status_code, 404)
        self.assertEqual(self.start(self.published_id, mode="TEST").status_code, 404)
        self.assertEqual(self.start(self.published_id, mode="PRACTICE").status_code, 201)

    def test_admin_and_test_student_can_start_drafts_only_as_test(self):
        for name in ["admin", "tester"]:
            client = self.login(name, self.app.test_client())
            self.assertIn("Trần Ngọc Linh", client.get("/cases").get_data(as_text=True))
            self.assertEqual(self.start(client=client, mode="PRACTICE").status_code, 404)
            self.assertEqual(self.start(client=client).status_code, 201)
        self.login()
        self.assertEqual(self.start(self.published_id, mode="PRACTICE").status_code, 404)

    def test_html_start_prg_reload_and_resume_keep_one_session_and_opening(self):
        self.login()
        response = self.client.get(f"/cases/{self.female_id}")
        form = HiddenInputs(response.get_data(as_text=True)).values
        first = self.client.post(f"/cases/{self.female_id}", data=form)
        self.assertEqual(first.status_code, 302)
        duplicate = self.client.post(f"/cases/{self.female_id}", data=form)
        self.assertEqual(duplicate.location, first.location)
        for _ in range(3):
            page = self.client.get(first.location)
            self.assertEqual(page.status_code, 200)
            self.assertIn("patient-female.png", page.get_data(as_text=True))
            self.assertIn("Trần Ngọc Linh", page.get_data(as_text=True))
        with self.app.app_context():
            self.assertEqual(self.count(SimulationSession), 1)
            self.assertEqual(self.count(Message), 1)
            item = db.session.scalar(db.select(SimulationSession))
            version = db.session.get(CaseVersion, self.female_id)
            self.assertEqual(item.state_json, version.content_json["initial_state"])
            self.assertEqual((item.state_version, item.turn_index, item.mode), (0,0,"TEST"))
            self.assertEqual(db.session.scalar(db.select(Message)).sender, "PATIENT")
        dashboard = self.client.get("/dashboard").get_data(as_text=True)
        self.assertIn(first.location, dashboard)
        self.assertIn("Tiếp tục", dashboard)

    def test_request_key_replay_and_conflicting_payload(self):
        self.login()
        key = uuid4().hex
        first = self.start(key=key)
        again = self.start(key=key)
        self.assertEqual((first.status_code, again.status_code), (201,200))
        self.assertEqual(first.get_json()["data"]["session_id"], again.get_json()["data"]["session_id"])
        self.assertFalse(again.get_json()["data"]["created"])
        conflict = self.start(version=self.male_id, key=key)
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.get_json()["error"]["code"], "REQUEST_CONFLICT")

    def test_new_sessions_have_independent_state_and_cannot_be_read_by_other_users(self):
        self.login()
        first = self.start().get_json()["data"]["session_id"]
        second = self.start().get_json()["data"]["session_id"]
        with self.app.app_context():
            item = db.session.get(SimulationSession, first)
            item.state_json = {"state_id":"S2", "cooperation":-1, "revealed_fact_ids":["F01"], "event_codes":[]}
            db.session.commit()
            self.assertEqual(db.session.get(SimulationSession, second).state_json["state_id"], "S0")
            self.assertEqual(db.session.get(CaseVersion, self.female_id).content_json["initial_state"]["state_id"], "S0")
        other = self.login("tester", self.app.test_client())
        for identifier in [first,second]:
            self.assertEqual(other.get(f"/sessions/{identifier}").status_code, 404)
            self.assertEqual(other.get(f"/api/v1/sessions/{identifier}/state").status_code, 404)

    def test_archiving_blocks_new_start_but_keeps_resume_and_replay(self):
        self.login()
        key = uuid4().hex
        identifier = self.start(key=key).get_json()["data"]["session_id"]
        with self.app.app_context():
            db.session.get(CaseVersion, self.female_id).status = "ARCHIVED"
            db.session.commit()
        self.assertEqual(self.client.get(f"/cases/{self.female_id}").status_code, 404)
        self.assertNotIn("Trần Ngọc Linh", self.client.get("/cases").get_data(as_text=True))
        self.assertEqual(self.start().status_code, 404)
        self.assertEqual(self.start(key=key).status_code, 200)
        self.assertEqual(self.client.get(f"/sessions/{identifier}").status_code, 200)
        self.assertEqual(self.client.get(f"/api/v1/sessions/{identifier}/state").get_json()["data"]["case"]["version_id"], self.female_id)

    def test_quota_includes_test_and_abandoned_but_not_replayed_request(self):
        self.login()
        keys = [uuid4().hex for _ in range(3)]
        for key in keys:
            self.assertEqual(self.start(key=key).status_code, 201)
        with self.app.app_context():
            item = db.session.scalar(db.select(SimulationSession))
            item.status, item.ended_at = "ABANDONED", utc_now()
            db.session.commit()
        response = self.start()
        self.assertEqual(response.status_code, 429)
        self.assertGreater(int(response.headers["Retry-After"]), 0)
        self.assertEqual(response.get_json()["error"]["code"], "DAILY_SESSION_LIMIT")
        self.assertEqual(self.start(key=keys[0]).status_code, 200)
        self.assertEqual(self.client.get("/dashboard").status_code, 200)

    def test_concurrent_new_requests_do_not_exceed_quota(self):
        self.app.config["SESSION_DAILY_LIMIT"] = 1
        clients = [self.login(client=self.app.test_client()) for _ in range(2)]
        tokens = [self.csrf(c) for c in clients]
        barrier = Barrier(2)
        def send(index):
            barrier.wait(timeout=10)
            return clients[index].post("/api/v1/sessions", json={"case_version_id":self.female_id,
                "mode":"TEST", "request_key":uuid4().hex}, headers={"X-CSRFToken":tokens[index]}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(send, [0,1]))
        self.assertEqual(sorted(statuses), [201,429])
        with self.app.app_context():
            self.assertEqual(self.count(SimulationSession), 1)
            self.assertEqual(self.count(Message), 1)

    def test_concurrent_same_key_creates_one_session(self):
        clients = [self.login(client=self.app.test_client()) for _ in range(2)]
        tokens = [self.csrf(c) for c in clients]
        barrier, key = Barrier(2), uuid4().hex
        def send(index):
            barrier.wait(timeout=10)
            response = clients[index].post("/api/v1/sessions", json={"case_version_id":self.female_id,
                "mode":"TEST", "request_key":key}, headers={"X-CSRFToken":tokens[index]})
            return response.status_code, response.get_json()["data"]["session_id"]
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(send, [0,1]))
        self.assertEqual(sorted(r[0] for r in results), [200,201])
        self.assertEqual(results[0][1], results[1][1])

    def test_failed_commit_rolls_back_session_message_and_audit(self):
        self.login()
        token = self.csrf(self.client)
        with patch.object(db.session, "commit", side_effect=RuntimeError("commit fixture failure")):
            with self.assertRaises(RuntimeError):
                self.client.post("/api/v1/sessions", json={"case_version_id":self.female_id,
                    "mode":"TEST", "request_key":uuid4().hex}, headers={"X-CSRFToken":token})
        with self.app.app_context():
            self.assertEqual(self.count(SimulationSession), 0)
            self.assertEqual(self.count(Message), 0)
            self.assertIsNone(db.session.scalar(db.select(AuditLog).where(AuditLog.action == "SESSION_STARTED")))

    def test_input_validation_csrf_and_no_private_payload(self):
        self.login("student")
        self.assertEqual(self.client.post("/api/v1/sessions", json={}).status_code, 400)
        self.assertEqual(self.client.post(f"/cases/{self.published_id}", data={}).status_code, 400)
        token = self.csrf(self.client)
        for payload in [[], {}, {"case_version_id":True,"mode":"PRACTICE","request_key":uuid4().hex},
                        {"case_version_id":self.published_id,"mode":"PRACTICE","request_key":"tiny"},
                        {"case_version_id":self.published_id,"mode":"PRACTICE","request_key":uuid4().hex,"user_id":1}]:
            with self.subTest(payload=payload):
                response = self.client.post("/api/v1/sessions", json=payload, headers={"X-CSRFToken":token})
                self.assertEqual(response.status_code, 400)
        response = self.start(self.published_id, "PRACTICE")
        for secret in ["PRIVATE_FACT_NEVER_EXPOSE", "rules", "rubric", "state_json", "review_json"]:
            self.assertNotIn(secret, response.get_data(as_text=True))
            self.assertNotIn(secret, self.client.get(f"/cases/{self.published_id}").get_data(as_text=True))
        saved = response.get_json()["data"]["session"]
        self.assertEqual([f["fact_id"] for f in saved["facts"]], ["F01"])
        self.assertNotIn("facts", saved["case"])

    def test_version_is_pinned_when_new_case_version_is_published(self):
        self.login("student")
        identifier = self.start(self.published_id, "PRACTICE").get_json()["data"]["session_id"]
        with self.app.app_context():
            old = db.session.get(CaseVersion, self.published_id)
            old.status = "ARCHIVED"
            db.session.flush()
            db.session.add(CaseVersion(case_id=old.case_id, version_no=2, created_by_id=1,
                title="Phiên bản mới", status="PUBLISHED", demo_only=0, content_json=deepcopy(old.content_json),
                review_json={"fixture":True}, content_hash="e"*64))
            db.session.commit()
        state = self.client.get(f"/api/v1/sessions/{identifier}/state").get_json()["data"]
        self.assertEqual(state["case"]["version_id"], self.published_id)
        self.assertEqual(state["case"]["version_no"], 1)
        self.assertNotIn("Phiên bản mới", self.client.get(f"/sessions/{identifier}").get_data(as_text=True))

    def test_dashboard_latest_valid_score_excludes_test_other_user_and_failed_grading(self):
        with self.app.app_context():
            active = self.fixture_session()
            completed = self.fixture_session(status="COMPLETED", assisted=1)
            zero = self.fixture_session(status="COMPLETED")
            abandoned = self.fixture_session(status="ABANDONED")
            test = self.fixture_session(mode="TEST", status="COMPLETED")
            other = self.fixture_session(user=3, status="COMPLETED")
            ids = [active.id, completed.id, zero.id, abandoned.id, test.id, other.id]
            for row, number, status, total in [(completed,1,"VALID",80),(completed,2,"VALID",160),
                (completed,3,"ERROR",None),(zero,1,"VALID",0),(test,1,"VALID",200),(other,1,"VALID",200)]:
                db.session.add(Evaluation(session_id=row.id, case_version_id=row.case_version_id,
                    evaluation_no=number, status=status, total_points_x2=total, input_hash="f"*64))
            db.session.get(User, 2).is_test_account = 1
            db.session.commit()
            data = dashboard_data(db.session.get(User, 2))
            self.assertEqual((data["active_count"],data["closed_count"],data["valid_count"],data["test_count"]), (1,3,2,1))
            self.assertEqual(data["scores"], {completed.id:80.0, zero.id:0.0})
        self.login("student")
        html = self.client.get("/dashboard").get_data(as_text=True)
        self.assertIn("80.0/100", html)
        self.assertIn("0.0/100", html)
        self.assertIn("Có hỗ trợ", html)
        self.assertNotIn(f'href="/sessions/{ids[-1]}"', html)
        self.assertIn("Lượt này đã kết thúc", self.client.get(f"/sessions/{ids[1]}").get_data(as_text=True))

    def test_revoked_user_cannot_create_and_vietnam_day_boundary(self):
        with self.app.app_context():
            with self.assertRaises(PracticeError) as raised:
                start_session(1, 0, self.female_id, uuid4().hex, "TEST")
            self.assertEqual(raised.exception.status, 401)
            self.assertEqual(self.count(SimulationSession), 0)
        start, end, wait = day_window(datetime(2026,10,26,16,59,59,tzinfo=timezone.utc))
        self.assertEqual(start, "2026-10-25T17:00:00.000000Z")
        self.assertEqual(end, "2026-10-26T17:00:00.000000Z")
        self.assertEqual(wait, 1)


if __name__ == "__main__":
    unittest.main()
