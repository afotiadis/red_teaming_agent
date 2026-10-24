import json
import os
from typing import Dict, List

from src.coverage_tracker import CoverageTracker


MAX_HISTORY_SIZE = int(os.getenv("MAX_PLANNER_HISTORY", "50"))


class Planner:
    """Persist campaign history and objective/category coverage.

    The CrewAI strategist now owns prompt generation inside ``src.tasks``. This
    utility remains as the durable state holder used by the feedback loop and
    report builder.
    """

    def __init__(self, base_prompts: List[str] | None = None, base_prompt: str | None = None):
        self.state_path = os.getenv(
            "PLANNER_STATE_PATH",
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "planner_state.json"),
        )
        self.rag_top_k = int(os.getenv("RAG_TOP_K", "3"))
        self.user_prompt = base_prompt or "Security evaluation"
        self.history: List[Dict] = []
        self.coverage_tracker = CoverageTracker()
        self._load_from_disk()

    def record(self, prompt: str, status: str, latency: float, raw_response: str):
        """Add a run to the internal history and persist."""
        self.history.append(
            {
                "prompt": prompt,
                "status": status,
                "latency": latency,
                "raw": raw_response,
            }
        )
        self._save_to_disk()

    def update_coverage(self, feedback_summary: dict):
        self.coverage_tracker.update_from_feedback(feedback_summary)

    def get_coverage_summary(self) -> dict:
        return self.coverage_tracker.get_summary()

    def _successful_prompts(self) -> List[str]:
        return [h["prompt"] for h in self.history if "success" in h["status"].lower() or "200" in h["status"]]

    def _load_from_disk(self) -> None:
        try:
            with open(self.state_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.history = data.get("history", [])
        except FileNotFoundError:
            self.history = []
        except Exception as e:
            print(f"[Planner] Failed to load state: {e}")
            self.history = []

        try:
            with open(self.state_path + ".cov", "r", encoding="utf-8") as f:
                self.coverage_tracker.status = json.load(f)
        except Exception:
            pass

    def _save_to_disk(self) -> None:
        """Save current planner history and coverage, pruning old entries."""
        if len(self.history) > MAX_HISTORY_SIZE:
            self.history = self.history[-MAX_HISTORY_SIZE:]
        try:
            with open(self.state_path, "w", encoding="utf-8") as f:
                json.dump({"history": self.history}, f, indent=2)
            with open(self.state_path + ".cov", "w", encoding="utf-8") as f:
                json.dump(self.coverage_tracker.status, f, indent=2)
        except Exception as e:
            print(f"[Planner] Failed to save state: {e}")

    def to_json(self) -> str:
        return json.dumps(
            {
                "history": self.history,
                "coverage": self.coverage_tracker.get_summary(),
            },
            indent=2,
        )
