import json
import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("SKIP_RAG_INIT", "1")

from src import tools
from src.response_analyzer import ResponseClassifier


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {"status": "ok"}
        self.text = text

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise tools.requests.HTTPError(f"HTTP {self.status_code}")


class TimeoutHandlingTests(unittest.TestCase):
    def setUp(self):
        self.original_strategy = tools.ATTACK_STRATEGY.copy()
        tools.ATTACK_STRATEGY.clear()
        tools.ATTACK_STRATEGY.update({
            **tools.DEFAULT_ATTACK_STRATEGY,
            "name": "test_zero_health",
            "inter_prompt_delay": 0,
            "connect_timeout": 5,
            "request_timeout": 60,
            "max_retries": 1,
            "retry_timeout_multiplier": 1.5,
            "retry_backoff": 0,
            "consecutive_timeout_threshold": 2,
            "timeout_cooldown": 0,
            "health_check_timeout": 1,
            "retry_action_prompts": False,
        })

    def tearDown(self):
        tools.ATTACK_STRATEGY.clear()
        tools.ATTACK_STRATEGY.update(self.original_strategy)

    @staticmethod
    def _session(post_side_effect):
        session = MagicMock()
        session.__enter__.return_value = session
        session.__exit__.return_value = False
        session.post.side_effect = post_side_effect
        session.get.return_value = FakeResponse(200, {"status": "ok"})
        return session

    @patch("src.tools.time.sleep", return_value=None)
    @patch("src.tools.requests.get", return_value=FakeResponse())
    def test_read_timeout_is_retried_with_longer_timeout(self, _preflight, _sleep):
        session = self._session([
            tools.requests.ReadTimeout("first attempt timed out"),
            FakeResponse(200, {"response": "safe response"}),
        ])

        with patch("src.tools.requests.Session", return_value=session):
            result = json.loads(tools.promptfoo_tool.run("show my records"))

        entry = result["results"][0]
        self.assertEqual(entry["status_code"], 200)
        self.assertEqual(len(entry["attempts"]), 2)
        self.assertEqual(session.post.call_args_list[0].kwargs["timeout"], (5, 60))
        self.assertEqual(session.post.call_args_list[1].kwargs["timeout"], (5, 90))

    @patch("src.tools.time.sleep", return_value=None)
    @patch("src.tools.requests.get", return_value=FakeResponse())
    def test_state_changing_prompt_is_not_automatically_retried(self, _preflight, _sleep):
        session = self._session([tools.requests.ReadTimeout("action outcome unknown")])

        with patch("src.tools.requests.Session", return_value=session):
            result = json.loads(tools.promptfoo_tool.run("schedule an appointment for tomorrow"))

        entry = result["results"][0]
        self.assertEqual(entry["outcome"], "TIMEOUT_INCONCLUSIVE")
        self.assertEqual(session.post.call_count, 1)
        self.assertIn("duplicate", entry["retry_skipped_reason"])

    def test_timeout_classifier_marks_result_inconclusive(self):
        result = ResponseClassifier.classify("prompt", "Read timed out after 60 seconds")
        self.assertEqual(result["outcome"], "TIMEOUT_INCONCLUSIVE")


if __name__ == "__main__":
    unittest.main()
