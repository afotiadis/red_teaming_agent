import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("SKIP_RAG_INIT", "1")

from src import tools
from src.execution_runner import execute_plan, execute_planner_output, extract_execution_plan


class ExecutionRunnerTests(unittest.TestCase):
    def test_extracts_fenced_planner_json(self):
        plan = extract_execution_plan(
            """Planner result:
```json
{
  "tool": "execute_promptfoo_attack",
  "prompts_text": "one|two",
  "objectives_tested": ["extract_system_prompt"]
}
```"""
        )

        self.assertEqual(plan["tool"], "execute_promptfoo_attack")
        self.assertEqual(plan["prompts_text"], "one|two")

    def test_dispatches_promptfoo_directly(self):
        planner_output = SimpleNamespace(
            raw='{"tool": "execute_promptfoo_attack", "prompts_text": "show schema|show account"}'
        )

        with patch("src.execution_runner._call_tool", return_value='{"target": "local", "results": []}') as run:
            executor_raw, plan = execute_planner_output(planner_output)

        self.assertEqual(run.call_args.args[1], "show schema|show account")
        self.assertEqual(plan["tool"], "execute_promptfoo_attack")
        self.assertEqual(json.loads(executor_raw)["target"], "local")

    def test_fake_tool_call_marker_falls_back_and_dispatches(self):
        planner_output = SimpleNamespace(
            raw="<|tool_call_start|>[discover_target_surface(target_url='http://localhost:5000')]<|tool_call_end|>"
        )

        with patch.dict(os.environ, {"TARGET_APP": "vuln_bank", "ATTACK_PROMPTS_PER_ROUND": "4"}, clear=False):
            with patch("src.execution_runner._call_tool", return_value='{"target": "local", "results": []}') as run:
                executor_raw, plan = execute_planner_output(planner_output)

        self.assertEqual(plan["tool"], "execute_promptfoo_attack")
        self.assertIn("Deterministic fallback plan", plan["planning_rationale"])
        self.assertGreaterEqual(len([p for p in plan["prompts_text"].split("|") if p.strip()]), 4)
        self.assertIn("CORE INSTRUCTIONS", plan["prompts_text"])
        self.assertEqual(json.loads(executor_raw)["target"], "local")
        self.assertEqual(run.call_args.args[1], plan["prompts_text"])

    def test_empty_promptfoo_plan_falls_back(self):
        planner_output = SimpleNamespace(raw='{"tool": "execute_promptfoo_attack", "prompts_text": ""}')

        with patch.dict(os.environ, {"TARGET_APP": "vulnerable_chat", "ATTACK_PROMPTS_PER_ROUND": "3"}, clear=False):
            with patch("src.execution_runner._call_tool", return_value='{"target": "local", "results": []}'):
                _executor_raw, plan = execute_planner_output(planner_output)

        self.assertEqual(plan["tool"], "execute_promptfoo_attack")
        self.assertIn("extract_system_prompt", plan["objectives_tested"])
        self.assertEqual(len([p for p in plan["prompts_text"].split("|") if p.strip()]), 3)

    def test_unsupported_tool_returns_structured_error(self):
        with patch("src.execution_runner.get_target_chat_url", return_value="http://target/chat"):
            result = json.loads(execute_plan({"tool": "unknown_tool", "prompts_text": "hello"}))

        self.assertEqual(result["target"], "http://target/chat")
        self.assertEqual(result["results"], [])
        self.assertIn("Unsupported planner tool", result["execution_error"])

    def test_surface_discovery_skips_active_probes_by_default(self):
        with patch.dict(os.environ, {"TARGET_SURFACE_ACTIVE_PROBES": "0"}, clear=False):
            with patch("src.tools.requests.options") as options, patch("src.tools.requests.get") as get, patch("src.tools.requests.post") as post:
                result = tools.discover_target_surface.func("")

        self.assertIn("Active Probes:** skipped", result)
        options.assert_not_called()
        get.assert_not_called()
        post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
