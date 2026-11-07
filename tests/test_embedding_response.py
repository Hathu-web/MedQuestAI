"""Regression cho bộ đọc embedding; hoàn toàn mock, không gọi API hoặc dùng DB."""
from copy import deepcopy
import unittest
from unittest.mock import patch
import numpy as np

from app.ai.embeddings import Embedder, openai_vectors
from app.ai.errors import AIError
from app.ai.settings import DEFAULTS


def gemini_config(**changes):
    return {**DEFAULTS, "TESTING": True, "EMBED_PROVIDER": "openai",
            "EMBED_BASE_URL": "https://generativelanguage.googleapis.com/v1beta/openai/",
            "EMBED_MODEL": "gemini-embedding-001", "EMBED_API_KEY": "mock-only", **changes}


class EmbeddingResponseTests(unittest.TestCase):
    def test_one_input_one_embedding_can_recover_missing_zero_for_gemini(self):
        with patch("app.ai.embeddings.post_json", return_value={"data": [{"embedding": [3., 4.]}]}):
            result = Embedder(gemini_config()).embed(["one input"])
        np.testing.assert_allclose(result, [[.6, .8]])

    def test_batch_uses_explicit_indices_to_recover_zero_not_list_position(self):
        response = {"data": [{"index": 2, "embedding": [0, 0, 2]},
                             {"embedding": [2, 0, 0]}, {"index": 1, "embedding": [0, 2, 0]}]}
        original = deepcopy(response)
        with patch("app.ai.embeddings.post_json", return_value=response) as request:
            result = Embedder(gemini_config()).embed(["first", "second", "third"])
        np.testing.assert_allclose(result, np.eye(3))
        self.assertEqual(response, original)
        self.assertEqual(request.call_count, 1)
        self.assertEqual(request.call_args.args[0], "https://generativelanguage.googleapis.com/v1beta/openai/embeddings")

    def test_complete_indices_still_sort_and_validate(self):
        result = openai_vectors({"data": [{"index": 1, "embedding": [1, 2]},
                                          {"index": 0, "embedding": [3, 4]}]}, 2)
        self.assertEqual(result, [[3, 4], [1, 2]])

    def test_other_hosts_and_native_gemini_path_do_not_get_compatibility_exception(self):
        for base in ("https://api.example/v1", "https://generativelanguage.googleapis.com/v1beta",
                     "https://generativelanguage.googleapis.com.example/v1beta/openai/"):
            with self.subTest(base=base), patch("app.ai.embeddings.post_json", return_value={"data": [{"embedding": [1, 2]}]}):
                with self.assertRaises(AIError):
                    Embedder(gemini_config(EMBED_BASE_URL=base)).embed(["first"])

    def test_multiple_missing_indices_or_missing_nonzero_are_rejected(self):
        for rows in ([{"embedding": [1]}, {"embedding": [2]}],
                     [{"index": 0, "embedding": [1]}, {"embedding": [2]}]):
            with self.subTest(rows=rows), self.assertRaises(AIError):
                openai_vectors({"data": rows}, 2, allow_missing_zero=True)

    def test_duplicate_out_of_range_and_wrong_type_indices_are_rejected(self):
        bad = [None, True, False, 0.0, "0", -1, 1, [], {}]
        for index in bad:
            with self.subTest(index=index), self.assertRaises(AIError):
                openai_vectors({"data": [{"index": index, "embedding": [1]}]}, 1, allow_missing_zero=True)
        with self.assertRaises(AIError):
            openai_vectors({"data": [{"index": 1, "embedding": [1]}, {"index": 1, "embedding": [2]}]}, 2, allow_missing_zero=True)

    def test_wrong_counts_empty_data_and_missing_embedding_are_rejected(self):
        responses = [{"data": []}, {"data": {}}, {"data": None}, {"data": [None]},
                     {"data": [{"index": 0}]}, {"data": [{"index": 0, "embedding": [1]}] * 2}]
        for response in responses:
            with self.subTest(response=response), self.assertRaises(AIError) as error:
                openai_vectors(response, 1, allow_missing_zero=True)
            self.assertEqual(error.exception.code, "EMBED_INVALID")

    def test_native_shapes_and_embedded_errors_are_identified_without_raw_response_leaks(self):
        for response, fragment in (({"embedding": {"values": [1, 2]}}, "adapter openai cần data"),
                                   ({"error": {"message": "DO_NOT_PRINT_SECRET"}}, "trường error"),
                                   ({}, "thiếu trường data")):
            with self.subTest(response=response), self.assertRaises(AIError) as error:
                openai_vectors(response, 1, allow_missing_zero=True)
            self.assertIn(fragment, str(error.exception))
            self.assertNotIn("DO_NOT_PRINT_SECRET", str(error.exception))

    def test_missing_zero_does_not_bypass_numeric_validation(self):
        for vector in ([], [0, 0], [float("nan"), 1], [float("inf"), 1], "base64-string", None):
            with self.subTest(vector=vector), patch("app.ai.embeddings.post_json", return_value={"data": [{"embedding": vector}]}):
                with self.assertRaises(AIError):
                    Embedder(gemini_config()).embed(["first"])

    def test_api_failure_is_propagated_without_another_request(self):
        with patch("app.ai.embeddings.post_json", side_effect=AIError("HTTP 429", "AI_HTTP_429")) as request:
            with self.assertRaises(AIError) as error:
                Embedder(gemini_config()).embed(["first"])
            self.assertEqual(error.exception.code, "AI_HTTP_429")
            self.assertEqual(request.call_count, 1)


if __name__ == "__main__":
    unittest.main()
