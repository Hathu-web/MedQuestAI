"""Kiểm thử hợp đồng chấm, dẫn chứng và HTTP/DB; không gọi LLM thật."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import unittest
from unittest.mock import patch
from uuid import uuid4

from werkzeug.security import generate_password_hash

from app.ai.errors import AIError
from app.ai.tutor import validate_result
from app.extensions import db
from app.models import AICall, AIOperation, Evaluation, EvaluationItem, Evidence, Message, RubricCriterion, SimulationSession, Submission, User
from tests import test_conversation as fixture


class TutorValidationTests(unittest.TestCase):
    def setUp(self):
        self.rubric = [{"criterion_code": code, "weight": weight, "evidence_sources": ["LEARNER_MESSAGE"]}
                       for code, weight in (("C01", 15), ("C02", 25), ("C03", 60))]
        self.sources = {"M1": {"kind": "LEARNER_MESSAGE", "text": "Chào em, chị xin phép hỏi vài điều."},
                        "S1": {"kind": "SUBMISSION", "text": "Chào em, chị xin phép hỏi vài điều."}}
        self.rows = [{"criterion_code": row["criterion_code"], "level": "MISSED",
            "reason": "Chưa thấy bằng chứng trong hồ sơ.", "suggestion": "Hỏi rõ điều cần tìm hiểu.", "evidence": []}
            for row in self.rubric]

    def grade(self, rows=None):
        return validate_result(json.dumps({"items": self.rows if rows is None else rows}, ensure_ascii=False), self.rubric, self.sources)

    def test_score_is_calculated_from_weights_including_half_points(self):
        for row, level in zip(self.rows[:2], ("ACHIEVED", "PARTIAL")):
            row.update(level=level, evidence=[{"source_id": "M1", "quote": "chị xin phép"}])
        result = self.grade()
        self.assertEqual(result["total_points_x2"], 55)
        self.assertEqual([r["points_x2"] for r in result["items"]], [30, 25, 0])

    def test_undetermined_never_becomes_zero_or_a_final_total(self):
        self.rows[0]["level"] = "UNDETERMINED"
        result = self.grade()
        self.assertEqual(result["status"], "NEEDS_REVIEW")
        self.assertIsNone(result["total_points_x2"])
        self.assertIsNone(result["items"][0]["points_x2"])

    def test_missing_duplicate_extra_and_model_supplied_score_are_rejected(self):
        candidates = [self.rows[:-1], self.rows + [self.rows[0]],
                      [self.rows[0], self.rows[0], self.rows[2]],
                      [{**self.rows[0], "points": 100}, *self.rows[1:]]]
        for rows in candidates:
            with self.subTest(rows=rows), self.assertRaises(AIError):
                self.grade(rows)

    def test_positive_level_requires_evidence(self):
        self.rows[0]["level"] = "ACHIEVED"
        with self.assertRaises(AIError):
            self.grade()

    def test_wrong_session_patient_source_and_wrong_source_type_are_rejected(self):
        for source in ("M999", "PATIENT1", "S1"):
            self.rows[0].update(level="PARTIAL", evidence=[{"source_id": source, "quote": "chị xin phép"}])
            with self.subTest(source=source), self.assertRaises(AIError):
                self.grade()

    def test_quote_must_be_exact_contiguous_and_offsets_point_to_original(self):
        self.rows[0].update(level="ACHIEVED", evidence=[{"source_id": "M1", "quote": "chị xin phép"}])
        proof = self.grade()["items"][0]["evidence"][0]
        self.assertEqual(self.sources["M1"]["text"][proof["start"]:proof["end"]], proof["quote"])
        for quote in ("Chị xin phép", "Chào ... hỏi", "", "Em bắt đầu mệt từ hôm qua"):
            self.rows[0]["evidence"][0]["quote"] = quote
            with self.subTest(quote=quote), self.assertRaises(AIError):
                self.grade()

    def test_rubric_weights_must_total_one_hundred(self):
        self.rubric[0]["weight"] = 16
        with self.assertRaises(AIError):
            self.grade()

    def test_json_fence_is_accepted_but_unknown_labels_and_chatter_are_not(self):
        raw = json.dumps({"items": self.rows})
        self.assertEqual(validate_result("```json\n" + raw + "\n```", self.rubric, self.sources)["status"], "VALID")
        with self.assertRaises(AIError):
            validate_result("Here is a grade: " + raw, self.rubric, self.sources)
        self.rows[0]["level"] = "PERFECT"
        with self.assertRaises(AIError):
            self.grade()


class TutorDatabaseTests(unittest.TestCase):
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
        self.app.config.update(AI_TUTOR_ENABLED=True, LLM_PROVIDER="openai", LLM_MODEL="test-tutor",
            LLM_BASE_URL="https://example.invalid/v1", LLM_API_KEY="MOCK_KEY")
        self.assertEqual(self.send(self.payload(text="Chào em, chị là sinh viên. Chị xin phép hỏi vài điều nhé?")).status_code, 200)
        self.summary = "Chưa đủ dữ kiện; cần hỏi thêm diễn biến trước khi kết luận."

    def close(self):
        return self.command("close", decision="SUBMIT", summary=self.summary)

    def assess(self, data=None, client=None, session_id=None):
        return self.send(data or {"request_key": uuid4().hex, "expected_state_version": self.state()["state_version"]},
                         endpoint="assessment", client=client, session_id=session_id)

    def reply(self, url, payload, key, timeout):
        self.assertFalse(db.session().in_transaction())
        self.assertEqual(payload["max_tokens"], self.app.config["AI_TUTOR_MAX_OUTPUT_TOKENS"])
        data = json.loads(payload["messages"][-1]["content"])
        self.assertNotIn("MOCK_KEY", str(payload))
        self.assertNotIn("password_hash", str(payload))
        rows = []
        for criterion in data["RUBRIC"]:
            code = criterion["criterion_code"]
            row = {"criterion_code": code, "level": "MISSED", "reason": "Chưa thấy bằng chứng trong hồ sơ.",
                   "suggestion": "Hỏi thêm một câu làm rõ tiêu chí này.", "evidence": []}
            if code == "C05":
                source = next(m for m in data["HOI_THOAI"] if m["speaker"] == "LEARNER")
                row.update(level="ACHIEVED", reason="Đã giới thiệu và xin phép.",
                    evidence=[{"source_id": source["evidence_source"], "quote": source["text"]}])
            elif code == "C07":
                source = data["TONG_KET"]
                row.update(level="PARTIAL", reason="Đã nêu giới hạn dữ kiện.",
                    evidence=[{"source_id": source["source_id"], "quote": source["text"]}])
            rows.append(row)
        return {"choices": [{"message": {"content": json.dumps({"items": rows}, ensure_ascii=False)}}],
                "usage": {"total_tokens": 300}}

    def test_submit_automatically_saves_score_items_evidence_and_reloads(self):
        with patch("app.ai.llm.post_json", side_effect=self.reply) as provider:
            response = self.close()
            self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
            self.assertEqual(provider.call_count, 1)
        assessment = response.get_json()["data"]["session"]["assessment"]
        self.assertEqual((assessment["status"], assessment["score"]), ("VALID", 20))
        self.assertEqual(len(assessment["items"]), 8)
        self.assertFalse(assessment["can_request"])
        with self.app.app_context():
            evaluation = db.session.scalar(db.select(Evaluation))
            self.assertEqual(evaluation.total_points_x2, 40)
            self.assertEqual(db.session.scalar(db.select(db.func.count()).select_from(Evidence)), 2)
            self.assertEqual(db.session.scalar(db.select(AICall)).stage, "TUTOR")
            self.assertIsNotNone(db.session.get(Submission, self.session_id))
        html = self.client.get(f"/sessions/{self.session_id}").get_data(as_text=True)
        self.assertIn("20/100", html)
        self.assertIn("không tính vào thống kê", html)

    def test_second_submit_and_new_grade_request_do_not_call_again(self):
        data = {"request_key": uuid4().hex, "expected_state_version": self.state()["state_version"],
                "decision": "SUBMIT", "summary": self.summary}
        with patch("app.ai.llm.post_json", side_effect=self.reply) as provider:
            self.assertEqual(self.send(data, "close").status_code, 200)
            self.assertEqual(self.send(data, "close").status_code, 200)
            self.assertFalse(self.assess().get_json()["data"]["created"])
            self.client.get(f"/sessions/{self.session_id}")
            self.assertEqual(provider.call_count, 1)

    def test_network_failure_keeps_completed_submission_without_zero_score(self):
        with patch("app.ai.llm.post_json", side_effect=AIError("Dịch vụ tạm quá tải", "AI_HTTP_503", uncertain=True)) as provider:
            response = self.close()
            self.assertEqual(response.status_code, 200)
            self.assertEqual(provider.call_count, 1)
        state = self.state()
        self.assertEqual(state["status"], "COMPLETED")
        self.assertEqual(state["summary"], self.summary)
        self.assertEqual(state["assessment"]["status"], "ERROR")
        self.assertIsNone(state["assessment"]["score"])
        self.assertTrue(state["assessment"]["can_request"])
        with self.app.app_context():
            self.assertEqual(db.session.scalar(db.select(AICall)).status, "UNKNOWN")
        with patch("app.ai.llm.post_json", side_effect=self.reply) as provider:
            self.assertEqual(self.assess().status_code, 200)
            self.assertEqual(provider.call_count, 1)
        self.assertEqual(self.state()["assessment"]["number"], 2)

    def test_invalid_evidence_does_not_save_any_grade_rows(self):
        def invalid(*args):
            result = self.reply(*args)
            data = json.loads(result["choices"][0]["message"]["content"])
            data["items"][4]["evidence"][0]["source_id"] = "M999999"
            result["choices"][0]["message"]["content"] = json.dumps(data)
            return result
        with patch("app.ai.llm.post_json", side_effect=invalid):
            self.assertEqual(self.close().status_code, 200)
        self.assertEqual(self.state()["assessment"]["status"], "ERROR")
        with self.app.app_context():
            self.assertEqual(db.session.scalar(db.select(db.func.count()).select_from(EvaluationItem)), 0)
            self.assertIsNone(db.session.scalar(db.select(Evaluation)).total_points_x2)

    def test_undetermined_saves_details_but_no_total_or_retry(self):
        def uncertain(*args):
            result = self.reply(*args)
            data = json.loads(result["choices"][0]["message"]["content"])
            data["items"][0]["level"] = "UNDETERMINED"
            result["choices"][0]["message"]["content"] = json.dumps(data)
            return result
        with patch("app.ai.llm.post_json", side_effect=uncertain):
            self.close()
        assessment = self.state()["assessment"]
        self.assertEqual(assessment["status"], "NEEDS_REVIEW")
        self.assertIsNone(assessment["score"])
        self.assertEqual(len(assessment["items"]), 8)
        self.assertFalse(assessment["can_request"])

    def test_active_abandoned_unauthorized_and_missing_csrf_do_not_call_provider(self):
        with patch("app.ai.llm.post_json") as provider:
            self.assertEqual(self.assess().status_code, 409)
            data = {"request_key": uuid4().hex, "expected_state_version": self.state()["state_version"]}
            other = self.login("other")
            self.assertEqual(self.assess(data, client=other).status_code, 404)
            self.assertEqual(self.client.post(f"/api/v1/sessions/{self.session_id}/assessment", json=data).status_code, 400)
            self.assertEqual(self.client.post(f"/sessions/{self.session_id}/assessment", data=data).status_code, 400)
            anonymous = self.app.test_client()
            self.assertEqual(anonymous.post(f"/api/v1/sessions/{self.session_id}/assessment", json=data,
                headers={"X-CSRFToken": self.csrf(anonymous)}).status_code, 401)
            self.command("close", decision="ABANDON", summary="")
            self.assertEqual(self.assess().status_code, 409)
            provider.assert_not_called()

    def test_disabled_and_demo_tutor_never_generate_fake_points(self):
        self.app.config["AI_TUTOR_ENABLED"] = False
        with patch("app.ai.llm.post_json") as provider:
            self.close()
            self.assertEqual(self.state()["assessment"]["status"], "NOT_STARTED")
            self.assertEqual(self.assess().status_code, 503)
            self.app.config.update(AI_TUTOR_ENABLED=True, LLM_PROVIDER="demo")
            self.assertEqual(self.assess().status_code, 503)
            provider.assert_not_called()

    def test_html_manual_grading_of_old_completed_session_and_xss_escaping(self):
        self.summary = '<script>alert("xss")</script> Chưa đủ dữ kiện.'
        self.app.config["AI_TUTOR_ENABLED"] = False
        self.close()
        self.app.config["AI_TUTOR_ENABLED"] = True
        path = f"/sessions/{self.session_id}"
        data = fixture.Forms(self.client.get(path).get_data(as_text=True)).forms[path + "/assessment"][0]
        with patch("app.ai.llm.post_json", side_effect=self.reply):
            self.assertEqual(self.client.post(path + "/assessment", data=data).status_code, 302)
        html = self.client.get(path).get_data(as_text=True)
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn('<script>alert("xss")</script>', html)
        self.assertNotIn("MOCK_KEY", html)

    def test_rubric_change_while_llm_runs_discards_stale_result(self):
        def changed(*args):
            result = self.reply(*args)
            criterion = db.session.scalar(db.select(RubricCriterion).where(RubricCriterion.case_version_id == self.versions[0]))
            criterion.description += " changed"
            db.session.commit()
            return result
        with patch("app.ai.llm.post_json", side_effect=changed):
            response = self.close()
            self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            self.assertEqual(db.session.scalar(db.select(Evaluation)).status, "ERROR")
            self.assertEqual(db.session.scalar(db.select(db.func.count()).select_from(EvaluationItem)), 0)

    def test_revoked_owner_during_call_cannot_finalize_grade(self):
        def revoked(*args):
            result = self.reply(*args)
            db.session.get(User, 1).auth_version += 1
            db.session.commit()
            return result
        with patch("app.ai.llm.post_json", side_effect=revoked):
            self.assertEqual(self.close().status_code, 401)
        with self.app.app_context():
            self.assertEqual(db.session.scalar(db.select(Evaluation)).status, "ERROR")
            self.assertEqual(db.session.scalar(db.select(db.func.count()).select_from(EvaluationItem)), 0)

    def test_retry_limit_and_quota_do_not_issue_extra_calls(self):
        self.app.config["AI_TUTOR_MAX_ATTEMPTS"] = 1
        with patch("app.ai.llm.post_json", side_effect=AIError("test failure")) as provider:
            self.close()
            self.assertEqual(self.assess().status_code, 429)
            self.assertEqual(provider.call_count, 1)
        self.assertFalse(self.state()["assessment"]["can_request"])
        self.app.config.update(AI_TUTOR_MAX_ATTEMPTS=3, AI_DAILY_CALL_LIMIT=1)
        with patch("app.ai.llm.post_json") as provider:
            response = self.assess()
            self.assertEqual(response.status_code, 429)
            self.assertEqual(response.get_json()["error"]["code"], "AI_DAILY_LIMIT")
            provider.assert_not_called()

    def test_oversized_context_is_not_truncated_and_misgraded(self):
        self.app.config["AI_TUTOR_ENABLED"] = False
        self.close()
        self.app.config.update(AI_TUTOR_ENABLED=True, AI_TUTOR_MAX_CONTEXT_CHARS=10000)
        with self.app.app_context():
            message = db.session.scalar(db.select(Message).where(Message.session_id == self.session_id, Message.sender == "LEARNER"))
            message.content_text = "a" * 20000
            db.session.commit()
        with patch("app.ai.llm.post_json") as provider:
            result = self.assess()
            self.assertEqual(result.status_code, 413)
            provider.assert_not_called()

    def test_expired_processing_can_be_recovered_without_get_writes(self):
        with patch("app.ai.llm.post_json", side_effect=AIError("test failure")):
            self.close()
        with self.app.app_context():
            evaluation = db.session.scalar(db.select(Evaluation))
            evaluation.status = "PROCESSING"
            operation = db.session.scalar(db.select(AIOperation).where(AIOperation.kind == "ASSESSMENT"))
            operation.status = "RUNNING"
            operation.started_at = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
            db.session.commit()
        self.assertEqual(self.state()["assessment"]["status"], "ERROR")
        with self.app.app_context():
            self.assertEqual(db.session.scalar(db.select(Evaluation)).status, "PROCESSING")
        with patch("app.ai.llm.post_json", side_effect=self.reply):
            self.assertEqual(self.assess().status_code, 200)
        self.assertEqual(self.state()["assessment"]["number"], 2)

    def test_prompt_is_session_scoped_and_excludes_undisclosed_patient_facts(self):
        other_id = self.start(self.versions[0])
        self.send(self.payload(text="OTHER_SESSION_SENTINEL"), session_id=other_id)
        with patch("app.ai.llm.post_json", side_effect=self.reply) as provider:
            self.close()
            sent = str(provider.call_args.args[1])
            self.assertNotIn("OTHER_SESSION_SENTINEL", sent)
            self.assertNotIn("Lo không đủ sức hoàn thành bài thi", sent)
            self.assertNotIn("password_hash", sent)

    def test_running_operation_prevents_a_second_provider_call(self):
        self.app.config["AI_TUTOR_ENABLED"] = False
        self.close()
        self.app.config["AI_TUTOR_ENABLED"] = True
        with self.app.app_context():
            db.session.add(AIOperation(session_id=self.session_id, request_key="busy-operation-key", input_hash="b"*64,
                kind="TURN", status="RUNNING", expected_state_version=0, input_payload_json={}))
            db.session.commit()
        with patch("app.ai.llm.post_json") as provider:
            response = self.assess()
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.get_json()["error"]["code"], "AI_BUSY")
            provider.assert_not_called()

    def test_html_submit_runs_tutor_and_error_page_offers_explicit_retry(self):
        path = f"/sessions/{self.session_id}"
        form = next(row for row in fixture.Forms(self.client.get(path).get_data(as_text=True)).forms[path + "/close"]
                    if row["decision"] == "SUBMIT")
        form["summary"] = self.summary
        with patch("app.ai.llm.post_json", side_effect=AIError("Dịch vụ tạm quá tải", "AI_HTTP_503")) as provider:
            response = self.client.post(path + "/close", data=form)
            self.assertEqual(response.status_code, 200)
            html = response.get_data(as_text=True)
            self.assertIn("Thử chấm lại", html)
            self.assertIn(self.summary, html)
            self.assertEqual(provider.call_count, 1)
        retry = fixture.Forms(html).forms[path + "/assessment"][0]
        with patch("app.ai.llm.post_json", side_effect=self.reply):
            self.assertEqual(self.client.post(path + "/assessment", data=retry).status_code, 302)


if __name__ == "__main__":
    unittest.main()
