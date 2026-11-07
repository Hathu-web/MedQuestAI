"""Câu hỏi mới, vector dễ gây nhầm, và ca v2 trên DB tạm; không gọi API thật."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np
from werkzeug.security import generate_password_hash

from app.extensions import db
from app.models import CaseVersion, SimulationSession, User
from app.ai.chunking import case_documents, digest
from app.ai.embeddings import Embedder
from app.ai.rag import finish_turn, plan_turn, select_intent
from app.ai.settings import DEFAULTS
from app.ai.vectorstore import index_case
from app.services.case_service import import_packages, load_package
from app.services.fake_patient import detect_intent, normalize
from app.services.scenario_engine import apply_event
from tests import test_conversation as fixture

ROOT = Path(__file__).resolve().parents[1]
UPDATE = ROOT / "data/case_updates/mq_com_01_v2.json"
QUESTIONS = (
    ("Bạn mô tả cụ thể mệt như nào", "ASK_DESCRIPTION", "F09"),
    ("mệt ở đâu", "ASK_LOCATION", "F10"),
    ("Em kể rõ hơn xem cảm giác mệt của em ra sao nhé", "ASK_DESCRIPTION", "F09"),
    ("Em thấy bộ phận nào bị mệt nhiều nhất vậy?", "ASK_LOCATION", "F10"),
    ("Em mệt mỏi kiểu gì, nói rõ giúp anh nhé?", "ASK_DESCRIPTION", "F09"),
    ("Em mệt mỏi ở đâu trên người?", "ASK_LOCATION", "F10"),
)


class RAGSpecificityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.v1 = json.loads((ROOT / "data/cases/mq_com_01_v1.json").read_text(encoding="utf-8"))["content"]
        cls.v2 = json.loads(UPDATE.read_text(encoding="utf-8"))["content"]

    def snapshot(self, content):
        docs = case_documents(content)
        rows = [{**row, "vector": np.array([1., 0.]), "source_hash": digest(docs)} for row in docs]
        return {"content": content, "rows": rows, "before": deepcopy(content["initial_state"]),
                "case_version_id": 2, "case_code": "MQ_COM_01", "version_no": 2}

    def config(self):
        return {**DEFAULTS, "TESTING": True, "EMBED_PROVIDER": "openai"}

    def test_old_case_never_forces_unsupported_aspect_into_onset(self):
        snap = self.snapshot(self.v1)
        # Chỉ một INTENT với cosine=1: trước bản vá semantic fallback chọn ONSET.
        snap["rows"] = [r for r in snap["rows"] if r["kind"] == "FACT" or r["source_id"] == "ASK_ONSET"]
        cfg = self.config()
        cfg.update(AI_HYBRID_ALPHA=1., AI_INTENT_MIN_SCORE=.4)
        for question, _, _ in QUESTIONS:
            with self.subTest(question=question):
                plan = plan_turn(snap, question, np.array([1., 0.]), cfg)
                self.assertIsNone(plan["intent"])
                self.assertEqual(plan["hits"], [])
                result = finish_turn(snap, plan)
                self.assertEqual(result["sources"], [])
                self.assertNotIn("hai tối trước", result["answer"])
                self.assertEqual(result["after"], snap["before"])

    def test_new_case_questions_retrieve_the_requested_aspect_only(self):
        snap = self.snapshot(self.v2)
        examples = {normalize(e) for row in self.v2["intents"] for e in row["examples"]}
        for question, intent, fid in QUESTIONS:
            with self.subTest(question=question):
                self.assertNotIn(normalize(question), examples)
                plan = plan_turn(snap, question, np.array([1., 0.]), self.config())
                self.assertEqual(plan["intent"], intent)
                self.assertEqual({r["source_id"] for r in plan["hits"]}, {fid})
                self.assertNotIn("hai tối trước", str(plan["hits"]))

    def test_explicit_multiple_questions_do_not_get_semantically_collapsed(self):
        snap = self.snapshot(self.v2)
        for question in ("Mệt ở đâu và bắt đầu thấy mệt từ khi nào?", "Thuốc và giấc ngủ"):
            with self.subTest(question=question):
                self.assertIsNone(select_intent(self.v2, snap["rows"], question, np.array([1., 0.]), self.config()))

    def test_conflicting_exact_examples_are_not_disambiguated_by_vectors(self):
        content = deepcopy(self.v2)
        for row in content["intents"][:2]:
            row["examples"].append("câu hỏi có hai nhãn")
        snap = self.snapshot(content)
        self.assertIsNone(select_intent(content, snap["rows"], "câu hỏi có hai nhãn", np.array([1., 0.]), self.config()))

    def test_all_v2_development_examples_and_branches_remain_valid(self):
        for example in self.v2["development_tests"]:
            with self.subTest(example=example["test_id"]):
                intent = detect_intent(self.v2, example["question"])
                self.assertEqual([intent], example["intent_ids"])
                result = apply_event(self.v2, example["initial"], intent)
                self.assertEqual([f["fact_id"] for f in result["facts"]], example["expected_fact_ids"])
                self.assertEqual(result["state"]["state_id"], example["expected_state"])
        for path in self.v2["branch_paths"]:
            state = deepcopy(path["initial"])
            for step in path["steps"]:
                state = apply_event(self.v2, state, step["event"])["state"]
                self.assertEqual(state["state_id"], step["expected_state"])

    def test_new_demo_facts_do_not_rewrite_old_facts_or_unknown_medication(self):
        self.assertEqual(self.v2["facts"][:len(self.v1["facts"])], self.v1["facts"])
        self.assertEqual(self.v2["rules"], self.v1["rules"])
        self.assertEqual(self.v2["facts"][6]["knowledge"], "UNKNOWN")
        package = json.loads(UPDATE.read_text(encoding="utf-8"))
        self.assertTrue(package["demo_only"])
        self.assertIn("hư cấu", package["review"]["source"])


class RAGSpecificityDatabaseTests(unittest.TestCase):
    cleanup = fixture.ConversationTests.cleanup
    csrf = fixture.ConversationTests.csrf
    login = fixture.ConversationTests.login
    start = fixture.ConversationTests.start
    state = fixture.ConversationTests.state
    payload = fixture.ConversationTests.payload
    send = fixture.ConversationTests.send
    command = fixture.ConversationTests.command

    @classmethod
    def setUpClass(cls):
        cls.password_hash = generate_password_hash(fixture.PASSWORD, method="scrypt")

    def setUp(self):
        fixture.ConversationTests.setUp(self)
        self.app.config.update(AI_CHAT_ENABLED=True, EMBED_PROVIDER="test")
        with self.app.app_context():
            for identifier in self.versions:
                index_case(identifier, Embedder())
        self.assertEqual(self.send().status_code, 200)
        self.old_session_id, self.before = self.session_id, self.state()
        with self.app.app_context():
            self.original = deepcopy(db.session.get(CaseVersion, self.versions[0]).content_json)
            self.users = [(u.id, u.password_hash) for u in db.session.scalars(db.select(User).order_by(User.id))]
            package = load_package(UPDATE)
            import_packages([package], "admin@example.com")
            self.version2 = db.session.scalar(db.select(CaseVersion.id).where(CaseVersion.version_no == 2))
            index_case(self.version2, Embedder())
        self.session_id = self.start(self.version2)
        self.app.config.update(LLM_PROVIDER="openai", LLM_MODEL="mock-model",
            LLM_BASE_URL="https://api.example/v1", LLM_API_KEY="MOCK_KEY")

    @staticmethod
    def response(_url, payload, _key, _timeout):
        context = json.loads(payload["messages"][-1]["content"])["NGU_CANH"]
        # Mô phỏng provider; đi qua validator LLM thật của ứng dụng.
        answer = {"answer": context[0]["text"] + " [1]", "citations": [1]}
        return {"choices": [{"message": {"content": json.dumps(answer, ensure_ascii=False)}}]}

    def test_import_preserves_existing_version_account_and_saved_conversation(self):
        # provider trên API là cấu hình hiện tại, không phải dữ liệu đã lưu.
        with patch.dict(self.app.config, {"LLM_PROVIDER": "demo"}):
            self.assertEqual(self.state(self.old_session_id), self.before)
        with self.app.app_context():
            old = db.session.get(CaseVersion, self.versions[0])
            self.assertEqual(old.content_json, self.original)
            self.assertEqual(db.session.get(SimulationSession, self.old_session_id).case_version_id, old.id)
            self.assertEqual([(u.id, u.password_hash) for u in db.session.scalars(db.select(User).order_by(User.id))], self.users)
            version = db.session.get(CaseVersion, self.version2)
            self.assertEqual((version.status, version.demo_only), ("DRAFT", 1))
            before_count = db.session.scalar(db.select(db.func.count()).select_from(CaseVersion))
            import_packages([load_package(UPDATE)], "admin@example.com")
            self.assertEqual(db.session.scalar(db.select(db.func.count()).select_from(CaseVersion)), before_count)

    def test_screenshot_questions_send_specific_sources_and_persist_after_reload(self):
        with patch("app.ai.llm.post_json", side_effect=self.response) as request:
            for question, _, fid in QUESTIONS[:2]:
                self.assertEqual(self.send(self.payload(text=question)).status_code, 200)
                latest = self.state()["messages"][-1]
                self.assertEqual(latest["reply_mode"], "rag_llm")
                self.assertEqual(len(latest["sources"]), 1)
                self.assertIn(fid, latest["sources"][0]["label"])
                self.assertIn("v2", latest["sources"][0]["label"])
                self.assertNotIn("hai tối trước", latest["text"])
                sent = request.call_args.args[1]["messages"]
                self.assertNotIn("hai tối trước", str(sent))
                self.assertNotIn("Lo không đủ sức", str(sent))
            self.assertEqual(request.call_count, 2)
        saved = self.state()
        self.assertEqual({f["fact_id"] for f in saved["facts"]}, {"F01", "F09", "F10"})
        html = self.client.get(f"/sessions/{self.session_id}").get_data(as_text=True)
        self.assertIn("uể oải", html)
        self.assertIn("mệt chung cả người", html)
        self.assertIn("Phản hồi LLM có nguồn", html)

    def test_old_session_cannot_use_new_version_facts_or_call_llm_for_missing_aspect(self):
        self.session_id = self.old_session_id
        with patch("app.ai.llm.post_json") as request:
            self.assertEqual(self.send(self.payload(text="mệt ở đâu")).status_code, 200)
            request.assert_not_called()
        latest = self.state()["messages"][-1]
        self.assertEqual(latest["sources"], [])
        self.assertIn("chưa có thông tin", latest["text"])
        self.assertNotIn("mệt chung cả người", latest["text"])
        self.assertNotIn("hai tối trước", latest["text"])

    def test_new_version_still_requires_permission_before_private_concern(self):
        with patch("app.ai.llm.post_json", side_effect=self.response) as request:
            self.assertEqual(self.send(self.payload(text=fixture.CONCERN)).status_code, 200)
            request.assert_not_called()
            self.assertEqual(self.command("actions", action_code="EXPLAIN_PRIVACY").status_code, 200)
            self.assertEqual(self.send(self.payload(text=fixture.CONCERN)).status_code, 200)
            self.assertEqual(request.call_count, 1)
        latest = self.state()["messages"][-1]
        self.assertIn("F06", latest["sources"][0]["label"])
        self.assertIn("Lo không đủ sức", latest["text"])


if __name__ == "__main__":
    unittest.main()
