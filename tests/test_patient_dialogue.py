"""Hội thoại tự do, nguồn và lịch sử của DB tạm; provider được giả lập."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from werkzeug.security import generate_password_hash

from app.extensions import db
from app.models import AICall, AIOperation, CaseVersion, SessionEvent, SimulationSession
from app.ai.chunking import case_documents, digest
from app.ai.embeddings import Embedder
from app.ai.errors import AIError
from app.ai.patient_dialogue import (build_patient_messages, recent_history, retrieval_queries,
    plan_patient_turn, validate_patient_answer, MISSING_NOTE)
from app.ai.settings import DEFAULTS
from app.ai.vectorstore import index_case
from app.services.case_service import import_packages, load_package
from app.services.fake_patient import detect_intent
from tests import test_conversation as fixture

ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / "data/case_updates/mq_com_01_v3.json"


def config():
    return {**DEFAULTS, "TESTING": True, "EMBED_PROVIDER": "test", "AI_TOP_K": 6,
            "AI_MAX_CONTEXT_CHARS": 4000}


class PatientDialogueUnitTests(unittest.TestCase):
    def setUp(self):
        self.content = json.loads(CASE.read_text(encoding="utf-8"))["content"]
        self.embedder = Embedder(config())
        docs = case_documents(self.content)
        vectors = []
        for i in range(0, len(docs), 32):
            vectors.extend(self.embedder.embed([d["search_text"] for d in docs[i:i+32]]))
        self.snapshot = {"content": self.content, "before": deepcopy(self.content["initial_state"]), "history": [],
            "rows": [{**d, "vector": v, "source_hash": digest(docs)} for d, v in zip(docs, vectors)]}

    def plan(self, question):
        queries = retrieval_queries(question, self.snapshot["history"])
        return plan_patient_turn(self.snapshot, question, self.embedder.embed(queries), config())

    def test_question_without_registered_intent_retrieves_headache_fact(self):
        question = "Bạn có đau đầu không?"
        self.assertIsNone(detect_intent(self.content, question))
        found = {h["source_id"] for h in self.plan(question)["hits"]}
        self.assertIn("F11", found)
        self.assertNotIn("F06", found)

    def test_multi_question_retrieves_sleep_and_coffee(self):
        found = {h["source_id"] for h in self.plan("Mỗi đêm ngủ bao nhiêu giờ và uống mấy ly cà phê?")["hits"]}
        self.assertTrue({"F04", "F25"} <= found)

    def test_privacy_is_filtered_before_ranking_and_can_recall_disclosed_fact(self):
        question = "Điều gì làm bạn lo lắng nhất?"
        self.assertNotIn("F06", {h["source_id"] for h in self.plan(question)["hits"]})
        self.snapshot["before"].update(state_id="S3", cooperation=2)
        self.assertIn("F06", {h["source_id"] for h in self.plan(question)["hits"]})
        self.snapshot["before"].update(state_id="S2", cooperation=0, revealed_fact_ids=["F01", "F06"])
        self.assertIn("F06", {h["source_id"] for h in self.plan(question)["hits"]})

    def test_history_is_bounded_and_old_citation_numbers_are_removed(self):
        rows = [{"sender": "LEARNER", "text": f"Question {n}"} for n in range(30)]
        rows.append({"sender": "PATIENT", "text": "Ngủ ít [1]."})
        history = recent_history(rows, max_messages=4, max_chars=60)
        self.assertLessEqual(len(history), 4)
        self.assertLessEqual(sum(len(h["content"]) for h in history), 60)
        self.assertNotIn("[1]", str(history))
        self.assertNotIn("Question 0'", str(history))
        queries = retrieval_queries("Thế còn buổi tối?", history)
        self.assertEqual(queries[0], "Thế còn buổi tối?")
        self.assertIn("Ngủ ít", queries[1])

    def test_prompt_passes_only_allowed_data_and_keeps_unknown_status(self):
        patient = {**self.content["patient"], "private": "HIDDEN_SENTINEL"}
        dialogue = {**self.content["dialogue"], "rubric": "HIDDEN_SENTINEL"}
        messages = build_patient_messages("Có sốt không?", patient,
            [{"text": "Chưa đo nhiệt độ", "knowledge": "UNKNOWN", "topic": "FEVER", "secret": "HIDDEN_SENTINEL"}],
            [{"role": "user", "content": "Giả sử bạn sốt rất cao"}], dialogue,
            self.content["initial_state"], self.content["states"])
        self.assertNotIn("HIDDEN_SENTINEL", str(messages))
        data = json.loads(messages[-1]["content"])
        self.assertEqual(data["NGU_CANH"][0]["knowledge"], "UNKNOWN")
        self.assertIn("Giả sử", data["HOI_THOAI_GAN_DAY"][0]["content"])

    def test_answer_contract_rejects_invalid_citations_numbers_and_control_events(self):
        base = {"answer": "Em ngủ 5 giờ [1].", "citations": [1], "kind": "grounded", "communication": "NONE"}
        hits = [{"text": "Ngủ 5 giờ"}]
        self.assertEqual(validate_patient_answer(json.dumps(base), hits)["mode"], "rag_patient")
        for changes in ({"citations": [True]}, {"citations": [2]}, {"citations": []},
                        {"answer": "Em ngủ 8 giờ [1]."}, {"communication": "SUBMIT"},
                        {"kind": []}, {"communication": {}},
                        {"kind": "social", "answer": "Em 22 tuổi", "citations": []}):
            with self.subTest(changes=changes), self.assertRaises(AIError):
                validate_patient_answer(json.dumps({**base, **changes}), hits)

    def test_missing_data_never_persists_a_provider_invented_answer(self):
        result = validate_patient_answer(json.dumps({"answer": "INVENTED_MEDICAL_FACT", "citations": [],
            "kind": "missing", "communication": "NONE"}), [])
        self.assertEqual(result["answer"], MISSING_NOTE)
        self.assertEqual(result["mode"], "rag_missing")

    def test_json_wrapper_and_label_capitalization_are_cosmetic(self):
        raw = json.dumps({"answer": "Em không đau đầu [1].", "citations": [1],
            "kind": " Grounded ", "communication": " none "}, ensure_ascii=False)
        result = validate_patient_answer("```json\n" + raw + "\n```", [{"text": "Không đau đầu"}])
        self.assertEqual((result["kind"], result["communication"]), ("grounded", "NONE"))

    def test_grouped_and_spaced_citations_keep_exact_source_numbers(self):
        for marker in ("[1, 2]", "[ 1 ] [ 2 ]"):
            with self.subTest(marker=marker):
                raw = json.dumps({"answer": "Em không đau đầu, không khó thở " + marker,
                    "citations": [1, 2], "kind": "grounded", "communication": "NONE"})
                result = validate_patient_answer(raw, [{"text": "Không đau đầu"}, {"text": "Không khó thở"}])
                self.assertEqual(result["citations"], [1, 2])
                self.assertIn("[1] [2]", result["answer"])

    def test_declared_sources_can_supply_missing_display_markers(self):
        raw = json.dumps({"answer": "Em không đau đầu.", "citations": [1],
            "kind": "grounded", "communication": "NONE"})
        result = validate_patient_answer(raw, [{"text": "Không đau đầu"}])
        self.assertEqual(result["answer"], "Em không đau đầu. [1]")

    def test_format_repair_does_not_accept_new_numbers_or_invalid_sources(self):
        base = {"answer": "Em ngủ 5 giờ", "citations": [1], "kind": "grounded", "communication": "NONE"}
        for changes in ({"answer": "Em ngủ 8 giờ"}, {"citations": []}, {"citations": [99]},
                        {"citations": [True]}, {"citations": [[1]]}, {"citations": ["1"]},
                        {"answer": "Em ngủ 5 giờ [2]"}, {"answer": "Em ngủ 5 giờ [1, 99]"}):
            with self.subTest(changes=changes), self.assertRaises(AIError):
                validate_patient_answer(json.dumps({**base, **changes}), [{"text": "Ngủ 5 giờ"}])

    def test_validation_error_explains_reason_without_exposing_raw_output(self):
        with self.assertRaises(AIError) as caught:
            validate_patient_answer(json.dumps({"answer": "Em ngủ 8 giờ [1].", "citations": [1],
                "kind": "grounded", "communication": "NONE"}), [{"text": "Ngủ 5 giờ"}])
        self.assertIn("số liệu không có trong nguồn", str(caught.exception))
        with self.assertRaises(AIError) as caught:
            validate_patient_answer("PRIVATE_RAW_SENTINEL", [])
        self.assertIn("JSON", str(caught.exception))
        self.assertNotIn("PRIVATE_RAW_SENTINEL", str(caught.exception))

    def test_redirect_needs_no_medical_source(self):
        result = validate_patient_answer(json.dumps({"answer": "Mình quay lại chuyện sức khỏe của em nhé?",
            "citations": [], "kind": "redirect", "communication": "NONE"}), [])
        self.assertEqual(result["mode"], "rag_dialogue")
        self.assertEqual(result["citations"], [])


class PatientDialogueDatabaseTests(unittest.TestCase):
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
        self.old_session = self.session_id
        self.app.config.update(AI_CHAT_ENABLED=True, EMBED_PROVIDER="test", AI_TOP_K=6,
            AI_MAX_CONTEXT_CHARS=4000, LLM_PROVIDER="openai", LLM_MODEL="test-model",
            LLM_BASE_URL="https://example.invalid/v1", LLM_API_KEY="MOCK_KEY")
        with self.app.app_context():
            self.old_content = deepcopy(db.session.get(CaseVersion, self.versions[0]).content_json)
            import_packages([load_package(CASE)], "admin@example.com")
            self.version = db.session.scalar(db.select(CaseVersion.id).where(CaseVersion.version_no == 3))
            index_case(self.version, Embedder())
        self.session_id = self.start(self.version)

    @staticmethod
    def raw(answer, citations=None, kind="grounded", communication="NONE"):
        return {"choices": [{"message": {"content": json.dumps({"answer": answer,
            "citations": citations or [], "kind": kind, "communication": communication}, ensure_ascii=False)}}]}

    def grounded(self, topic):
        def callback(_url, payload, _key, _timeout):
            self.assertFalse(db.session().in_transaction())
            context = json.loads(payload["messages"][-1]["content"])["NGU_CANH"]
            row = next(h for h in context if h["topic"] == topic)
            return self.raw(row["text"] + f" [{row['n']}]", [row["n"]])
        return callback

    def test_free_question_calls_real_adapter_and_saves_headache_source(self):
        with patch("app.ai.llm.post_json", side_effect=self.grounded("HEADACHE")) as request:
            self.assertEqual(self.send(self.payload(text="Bạn có đau đầu không?")).status_code, 200)
            self.assertEqual(request.call_count, 1)
        latest = self.state()["messages"][-1]
        self.assertEqual(latest["reply_mode"], "rag_patient")
        self.assertIn("F11", latest["sources"][0]["label"])
        self.assertIn("không bị đau đầu", latest["text"])
        self.assertNotRegex(latest["display_text"], r"\[\d+\]")
        html = self.client.get(f"/sessions/{self.session_id}").get_data(as_text=True)
        self.assertIn("Bệnh nhân AI", html)
        self.assertIn("không bị đau đầu", html)
        self.assertNotIn("Bộ phản hồi mẫu chỉ nhận", html)

    def test_followup_receives_saved_history_and_current_source(self):
        with patch("app.ai.llm.post_json", side_effect=self.grounded("SLEEP")):
            self.assertEqual(self.send(self.payload(text="Mỗi đêm ngủ được bao nhiêu giờ?")).status_code, 200)
        with patch("app.ai.llm.post_json", side_effect=self.grounded("SLEEP_QUALITY")) as request:
            self.assertEqual(self.send(self.payload(text="Thế có khó ngủ không?")).status_code, 200)
            sent = json.loads(request.call_args.args[1]["messages"][-1]["content"])
            self.assertIn("5 giờ", str(sent["HOI_THOAI_GAN_DAY"]))
            self.assertNotRegex(str(sent["HOI_THOAI_GAN_DAY"]), r"\[\d+\]")
        self.assertIn("F31", self.state()["messages"][-1]["sources"][0]["label"])

    def test_social_turn_calls_llm_even_without_retrieved_fact(self):
        reply = self.raw("Dạ, em chào anh. Mình bắt đầu nhé.", kind="social", communication="INTRO_PERMISSION")
        with patch("app.ai.patient_dialogue.search", return_value=[]), patch("app.ai.llm.post_json", return_value=reply) as request:
            self.assertEqual(self.send(self.payload(text="Chào em, anh xin phép trao đổi nhé.")).status_code, 200)
            self.assertEqual(request.call_count, 1)
        state = self.state()
        self.assertEqual(state["messages"][-1]["reply_mode"], "rag_dialogue")
        self.assertEqual(state["messages"][-1]["sources"], [])
        with self.app.app_context():
            self.assertEqual(db.session.get(SimulationSession, self.session_id).state_json["state_id"], "S1")

    def test_model_understands_communication_but_cannot_skip_disclosure_rules(self):
        intro = self.raw("Dạ, mình trao đổi nhé.", kind="social", communication="INTRO_PERMISSION")
        empathy = self.raw("Cảm ơn anh đã lắng nghe em.", kind="social", communication="EMPATHY")
        with patch("app.ai.llm.post_json", side_effect=[intro, empathy]) as request:
            self.assertEqual(self.send(self.payload(text="Chúng ta nói chuyện một chút nhé, em đồng ý chứ?")).status_code, 200)
            self.assertEqual(self.send(self.payload(text="Anh biết chuyện này không dễ với em, cứ từ từ thôi.")).status_code, 200)
            for call in request.call_args_list:
                self.assertNotIn("Lo không đủ sức", str(call.args[1]))
        with patch("app.ai.llm.post_json", side_effect=self.grounded("CONCERN")):
            self.assertEqual(self.send(self.payload(text="Điều gì làm em lo lắng nhất?")).status_code, 200)
        self.assertIn("F06", self.state()["messages"][-1]["sources"][0]["label"])

    def test_missing_information_is_a_case_note_not_patient_invented_fact(self):
        raw = self.raw("INVENTED_DIAGNOSIS", kind="missing")
        with patch("app.ai.llm.post_json", return_value=raw):
            self.assertEqual(self.send(self.payload(text="Ngày sinh đầy đủ của em là gì?")).status_code, 200)
        state = self.state()
        self.assertEqual(state["messages"][-1]["text"], MISSING_NOTE)
        self.assertEqual({f["fact_id"] for f in state["facts"]}, {"F01"})
        html = self.client.get(f"/sessions/{self.session_id}").get_data(as_text=True)
        self.assertIn("Ghi chú ca thực hành", html)
        self.assertNotIn("INVENTED_DIAGNOSIS", html)

    def test_history_is_scoped_to_the_current_session(self):
        first = self.session_id
        self.session_id = self.start(self.version)
        raw = self.raw("Dạ, em đang nghe.", kind="social")
        with patch("app.ai.llm.post_json", return_value=raw):
            self.assertEqual(self.send(self.payload(text="OTHER_SESSION_SENTINEL")).status_code, 200)
        self.session_id = first
        with patch("app.ai.llm.post_json", return_value=raw) as request:
            self.assertEqual(self.send(self.payload(text="Chào em")).status_code, 200)
            self.assertNotIn("OTHER_SESSION_SENTINEL", str(request.call_args.args[1]))

    def test_failed_or_duplicate_requests_do_not_double_save(self):
        payload = self.payload(text="Có đau đầu không?")
        with patch("app.ai.llm.post_json", side_effect=self.grounded("HEADACHE")) as request:
            self.assertEqual(self.send(payload).status_code, 200)
            self.assertFalse(self.send(payload).get_json()["data"]["created"])
            self.assertEqual(request.call_count, 1)
        before = self.state()
        with patch("app.ai.llm.post_json", return_value=self.raw("Sai nguồn [99]", [99])):
            self.assertEqual(self.send(self.payload(text="Có ho không?")).status_code, 502)
        self.assertEqual(self.state()["messages"], before["messages"])

    def test_import_keeps_old_version_and_cli_checks_retrieval_without_llm(self):
        with self.app.app_context():
            self.assertEqual(db.session.get(CaseVersion, self.versions[0]).content_json, self.old_content)
            self.assertEqual(db.session.get(SimulationSession, self.old_session).case_version_id, self.versions[0])
        with patch("app.ai.llm.post_json", side_effect=AssertionError("evaluate must not call LLM")):
            result = self.app.test_cli_runner().invoke(args=["ai", "evaluate", "--version-id", str(self.version)])
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("12/12", result.output)

    def test_open_case_does_not_silently_use_fake_answers_when_ai_is_disabled(self):
        self.app.config["AI_CHAT_ENABLED"] = False
        result = self.send(self.payload(text="Bạn có đau đầu không?"))
        self.assertEqual(result.status_code, 503)
        self.assertEqual(result.get_json()["error"]["code"], "AI_PATIENT_DISABLED")
        self.assertEqual(self.state()["turn_index"], 0)

    def test_remote_embedding_uses_one_batch_for_question_and_context(self):
        self.app.config.update(EMBED_PROVIDER="openai", EMBED_MODEL="mock-embedding",
            EMBED_BASE_URL="https://example.invalid/v1", EMBED_API_KEY="MOCK_KEY")
        def embedding(_url, payload, _key, _timeout):
            self.assertFalse(db.session().in_transaction())
            vectors = Embedder(config()).embed(payload["input"])
            return {"data": [{"index": i, "embedding": v.tolist()} for i, v in enumerate(vectors)]}
        with patch("app.ai.embeddings.post_json", side_effect=embedding) as embed:
            with self.app.app_context():
                index_case(self.version, Embedder())
            embed.reset_mock()
            with patch("app.ai.llm.post_json", side_effect=self.grounded("HEADACHE")):
                self.assertEqual(self.send(self.payload(text="Bạn có đau đầu không?")).status_code, 200)
            self.assertEqual(embed.call_count, 1)
            self.assertEqual(len(embed.call_args.args[1]["input"]), 2)
            self.assertEqual(embed.call_args.args[1]["input"][0], "Bạn có đau đầu không?")
        with self.app.app_context():
            calls = db.session.scalars(db.select(AICall).order_by(AICall.id)).all()
            self.assertEqual([c.stage for c in calls], ["EMBEDDING", "PATIENT"])
            self.assertTrue(all(c.status == "SUCCEEDED" for c in calls))

    def test_html_ai_failure_keeps_draft_and_refreshes_key_for_changed_question(self):
        path = f"/sessions/{self.session_id}"
        action = path + "/messages"
        data = fixture.Forms(self.client.get(path).get_data(as_text=True)).forms[action][0]
        data["text"] = "Câu hỏi đầu tiên chưa lưu"
        with patch("app.ai.llm.post_json", return_value=self.raw("Sai nguồn [99]", [99])) as request:
            response = self.client.post(action, data=data)
            self.assertEqual(response.status_code, 502)
            self.assertEqual(request.call_count, 1)
        html = response.get_data(as_text=True)
        fresh = fixture.Forms(html).forms[action][0]
        self.assertIn(data["text"], html)
        self.assertNotEqual(fresh["request_key"], data["request_key"])
        self.assertEqual(self.state()["turn_index"], 0)
        # Sửa form được trả về thì gửi được; tái dùng mã cũ vẫn bị chặn ở backend.
        with patch("app.ai.llm.post_json", side_effect=self.grounded("HEADACHE")) as request:
            conflict = self.client.post(action, data={**data, "text": "Em có đau đầu không?"})
            self.assertEqual(conflict.status_code, 409)
            request.assert_not_called()
            fresh["text"] = "Em có đau đầu không?"
            self.assertEqual(self.client.post(action, data=fresh).status_code, 302)
            self.assertEqual(self.client.post(action, data=fresh).status_code, 302)
            self.assertEqual(request.call_count, 1)
        self.assertEqual(self.state()["turn_index"], 1)
        with self.app.app_context():
            operations = db.session.scalars(db.select(AIOperation).order_by(AIOperation.id)).all()
            self.assertEqual([op.status for op in operations], ["FAILED", "SUCCEEDED"])

    def test_html_stale_form_refreshes_raw_version_after_another_tab_sends(self):
        path = f"/sessions/{self.session_id}"
        action = path + "/messages"
        data = fixture.Forms(self.client.get(path).get_data(as_text=True)).forms[action][0]
        with patch("app.ai.llm.post_json", side_effect=self.grounded("HEADACHE")) as request:
            self.assertEqual(self.send(self.payload(text="Có đau đầu không?")).status_code, 200)
            data["text"] = "Hỏi từ tab cũ"
            response = self.client.post(action, data=data)
            self.assertEqual(response.status_code, 409)
            self.assertEqual(request.call_count, 1)
            fresh = fixture.Forms(response.get_data(as_text=True)).forms[action][0]
            self.assertEqual(fresh["expected_state_version"], "1")
            fresh["text"] = "Em có đau đầu không?"
            self.assertEqual(self.client.post(action, data=fresh).status_code, 302)
            self.assertEqual(request.call_count, 2)

    def test_html_invalid_input_preserves_draft_without_calling_provider(self):
        path = f"/sessions/{self.session_id}"
        action = path + "/messages"
        data = fixture.Forms(self.client.get(path).get_data(as_text=True)).forms[action][0]
        data["text"] = "a" * 2001
        with patch("app.ai.llm.post_json") as request:
            response = self.client.post(action, data=data)
            self.assertEqual(response.status_code, 400)
            request.assert_not_called()
        html = response.get_data(as_text=True)
        self.assertIn(data["text"], html)
        self.assertIn("field-error", html)
        self.assertNotEqual(fixture.Forms(html).forms[action][0]["request_key"], data["request_key"])
        self.assertEqual(self.state()["turn_index"], 0)

    def test_html_off_topic_question_is_saved_with_llm_redirect(self):
        path = f"/sessions/{self.session_id}"
        action = path + "/messages"
        data = fixture.Forms(self.client.get(path).get_data(as_text=True)).forms[action][0]
        data["text"] = "Thủ đô nước Pháp là gì?"
        reply = self.raw("Mình quay lại chuyện sức khỏe của em nhé?", kind="redirect")
        with patch("app.ai.patient_dialogue.search", return_value=[]), patch("app.ai.llm.post_json", return_value=reply) as request:
            self.assertEqual(self.client.post(action, data=data).status_code, 302)
            self.assertEqual(request.call_count, 1)
        messages = self.state()["messages"]
        self.assertEqual(messages[-2]["text"], data["text"])
        self.assertEqual(messages[-1]["reply_mode"], "rag_dialogue")

    def test_html_network_failure_does_not_retry_provider_automatically(self):
        path = f"/sessions/{self.session_id}"
        action = path + "/messages"
        data = fixture.Forms(self.client.get(path).get_data(as_text=True)).forms[action][0]
        data["text"] = "Em có đau đầu không?"
        with patch("app.ai.llm.post_json", side_effect=AIError("Mất kết nối", "AI_NETWORK", uncertain=True)) as request:
            response = self.client.post(action, data=data)
            self.assertEqual(response.status_code, 503)
            self.assertEqual(request.call_count, 1)
        self.assertEqual(self.state()["turn_index"], 0)
        with self.app.app_context():
            self.assertEqual(db.session.scalar(db.select(AICall)).status, "UNKNOWN")
        fresh = fixture.Forms(response.get_data(as_text=True)).forms[action][0]
        self.assertNotEqual(fresh["request_key"], data["request_key"])

    def test_html_stale_summary_keeps_draft_with_current_version(self):
        path = f"/sessions/{self.session_id}"
        action = path + "/close"
        forms = fixture.Forms(self.client.get(path).get_data(as_text=True)).forms[action]
        data = next(form for form in forms if form["decision"] == "SUBMIT")
        with patch("app.ai.llm.post_json", side_effect=self.grounded("HEADACHE")):
            self.assertEqual(self.send(self.payload(text="Em có đau đầu không?")).status_code, 200)
        data["summary"] = "Bản tóm tắt đang soạn."
        response = self.client.post(action, data=data)
        self.assertEqual(response.status_code, 409)
        html = response.get_data(as_text=True)
        self.assertIn(data["summary"], html)
        fresh = next(form for form in fixture.Forms(html).forms[action] if form["decision"] == "SUBMIT")
        self.assertNotEqual(fresh["request_key"], data["request_key"])
        self.assertEqual(fresh["expected_state_version"], "1")
        fresh["summary"] = data["summary"]
        self.assertEqual(self.client.post(action, data=fresh).status_code, 302)
        self.assertEqual(self.state()["status"], "COMPLETED")


if __name__ == "__main__":
    unittest.main()
