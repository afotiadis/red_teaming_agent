import os
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ.setdefault("OPENROUTER_API_KEY", "test-key")

from src.openrouter_llm import OpenRouterLLM, _extract_assistant_text


def response(payload, status_code=200, text=""):
    result = MagicMock()
    result.status_code = status_code
    result.text = text
    result.json.return_value = payload
    return result


class OpenRouterResponseTests(unittest.TestCase):
    def llm(self):
        llm = OpenRouterLLM(model="test/model")
        llm.api_key = "test-key"
        llm.max_retries = 1
        llm.retry_backoff = 0
        llm.fallback_models = ["test/fallback"]
        return llm

    def test_null_content_is_retried_and_never_reaches_stop_processing(self):
        null_response = response({
            "choices": [{"message": {"content": None}, "finish_reason": "stop"}]
        })
        valid_response = response({
            "choices": [{"message": {"content": "valid planner output"}, "finish_reason": "stop"}]
        })

        with patch("src.openrouter_llm.requests.post", side_effect=[null_response, valid_response]) as mock_post:
            result = self.llm().call("plan an attack")

        self.assertEqual(result, "valid planner output")
        self.assertEqual(mock_post.call_args_list[0].kwargs["json"]["model"], "test/model")
        self.assertEqual(mock_post.call_args_list[1].kwargs["json"]["model"], "test/fallback")

    def test_structured_text_content_is_flattened(self):
        text, diagnostic = _extract_assistant_text({
            "choices": [{
                "message": {"content": [{"type": "text", "text": "part one"}, {"type": "text", "text": " part two"}]},
                "finish_reason": "stop",
            }]
        })

        self.assertEqual(text, "part one part two")
        self.assertIn("finish_reason='stop'", diagnostic)

    def test_repeated_null_content_raises_descriptive_error(self):
        null_response = response({
            "choices": [{"message": {"content": None}, "finish_reason": "length"}]
        })

        with patch("src.openrouter_llm.requests.post", side_effect=[null_response, null_response]):
            with self.assertRaisesRegex(RuntimeError, "using models.*test/model.*test/fallback"):
                self.llm().call("plan an attack")

    def test_reporter_output_is_not_truncated_at_observation(self):
        valid_response = response({
            "choices": [{
                "message": {"content": "Findings\nObservation details remain part of the report."},
                "finish_reason": "stop",
            }]
        })

        with patch("src.openrouter_llm.requests.post", return_value=valid_response):
            result = self.llm().call(
                "write report",
                from_agent=SimpleNamespace(role="Senior Security Auditor"),
            )

        self.assertEqual(result, "Findings\nObservation details remain part of the report.")

    def test_retired_model_404_advances_to_fallback(self):
        unavailable_response = response(
            {"error": {"message": "model unavailable"}},
            status_code=404,
            text='{"error":{"message":"model unavailable"}}',
        )
        valid_response = response({
            "choices": [{"message": {"content": "fallback response"}, "finish_reason": "stop"}]
        })

        with patch("src.openrouter_llm.requests.post", side_effect=[unavailable_response, valid_response]) as mock_post:
            result = self.llm().call("plan an attack")

        self.assertEqual(result, "fallback response")
        self.assertEqual(mock_post.call_args_list[1].kwargs["json"]["model"], "test/fallback")


if __name__ == "__main__":
    unittest.main()
