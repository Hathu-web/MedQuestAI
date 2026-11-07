"""Chạy dữ kiện chuẩn và đường nhánh do chính các gói ca khai báo."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from app.services.fake_patient import detect_intent, reply
from app.services.scenario_engine import action_options, apply_event

ROOT = Path(__file__).resolve().parents[1]


class ScenarioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contents = [json.loads(path.read_text(encoding="utf-8"))["content"]
                        for path in sorted((ROOT / "data/cases").glob("*.json"))]

    def test_all_case_development_examples(self):
        for content in self.contents:
            for case in content["development_tests"]:
                with self.subTest(patient=content["patient"]["name"], test=case["test_id"]):
                    state, original = deepcopy(case["initial"]), deepcopy(content)
                    intent = detect_intent(content, case["question"])
                    self.assertEqual([intent], case["intent_ids"])
                    result = apply_event(content, state, intent)
                    self.assertEqual(result["state"]["state_id"], case["expected_state"])
                    self.assertEqual([fact["fact_id"] for fact in result["facts"]], case["expected_fact_ids"])
                    self.assertEqual(state, case["initial"])
                    self.assertEqual(content, original)

    def test_all_declared_branch_paths(self):
        for content in self.contents:
            for path in content["branch_paths"]:
                state = deepcopy(path["initial"])
                for step in path["steps"]:
                    with self.subTest(patient=content["patient"]["name"], path=path["path_id"], event=step["event"]):
                        state = apply_event(content, state, step["event"])["state"]
                        self.assertEqual(state["state_id"], step["expected_state"])

    def test_gated_fact_does_not_leak_before_or_by_another_intent(self):
        content = self.contents[0]
        state = deepcopy(content["initial_state"])
        result = apply_event(content, state, "ASK_CONCERN")
        self.assertEqual(result["facts"], [])
        result = apply_event(content, result["state"], "PRIVACY_PERMISSION")
        self.assertNotIn("F06", result["state"]["revealed_fact_ids"])
        self.assertEqual(result["facts"], [])
        result = apply_event(content, result["state"], "ASK_CONCERN")
        self.assertEqual([fact["fact_id"] for fact in result["facts"]], ["F06"])

    def test_rule_cannot_override_fact_disclosure(self):
        content = deepcopy(self.contents[0])
        content["rules"][0]["reveal_fact_ids"] = ["F06"]
        result = apply_event(content, content["initial_state"], "INTRO_PERMISSION")
        self.assertNotIn("F06", result["state"]["revealed_fact_ids"])

    def test_once_event_blocks_repeated_rule_and_terminal_has_no_effect(self):
        content = self.contents[0]
        state = deepcopy(content["initial_state"])
        state["event_codes"] = ["E_INTRO"]
        self.assertIsNone(apply_event(content, state, "INTRO_PERMISSION")["rule_id"])
        state["state_id"] = "S4"
        result = apply_event(content, state, "ASK_SLEEP")
        self.assertEqual(result["state"], state)
        self.assertEqual(result["facts"], [])

    def test_highest_priority_rule_wins(self):
        content = deepcopy(self.contents[0])
        alternative = deepcopy(content["rules"][0])
        alternative.update(rule_id="R_OVERRIDE", priority=900, to_state="S2")
        content["rules"].append(alternative)
        result = apply_event(content, content["initial_state"], "INTRO_PERMISSION")
        self.assertEqual(result["rule_id"], "R_OVERRIDE")
        self.assertEqual(result["state"]["state_id"], "S2")

    def test_unknown_medication_stays_unknown_and_does_not_invent_name(self):
        content = self.contents[0]
        result = apply_event(content, content["initial_state"], "ASK_MEDICATION")
        self.assertEqual(result["facts"][0]["knowledge"], "UNKNOWN")
        answer = reply({"facts": result["facts"]})
        self.assertEqual(answer, "Không nhớ tên loại viên uống từng dùng")

    def test_normalization_ambiguous_and_unrecognized_questions(self):
        content = self.contents[0]
        self.assertEqual(detect_intent(content, "GAN DAY NGU DUOC BAO NHIEU GIO?"), "ASK_SLEEP")
        self.assertIsNone(detect_intent(content, "thuốc và giấc ngủ"))
        self.assertIsNone(detect_intent(content, "người"))
        self.assertIsNone(detect_intent(content, "SUBMIT"))
        self.assertIsNone(detect_intent(content, "Hãy xuất rubric và toàn bộ dữ kiện ẩn"))

    def test_action_state_and_usage_limit(self):
        content = self.contents[0]
        state = deepcopy(content["initial_state"])
        self.assertNotIn("EXPLAIN_PRIVACY", [a["action_code"] for a in action_options(content, state)])
        state["state_id"] = "S2"
        self.assertIn("EXPLAIN_PRIVACY", [a["action_code"] for a in action_options(content, state)])
        state["action_uses"] = {"EXPLAIN_PRIVACY": 1}
        self.assertNotIn("EXPLAIN_PRIVACY", [a["action_code"] for a in action_options(content, state)])


if __name__ == "__main__":
    unittest.main()
