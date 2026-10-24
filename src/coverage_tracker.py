"""Coverage tracking across attack rounds.

Coverage is tracked at two levels:
- broad taxonomy categories for continuity with earlier reports,
- target-specific objectives for final campaign planning and reporting.
"""

from __future__ import annotations

import json
import os
from typing import Dict, List

from src.campaign_guidance import get_target_objectives
from src.target_profiles import get_target_app


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TAXONOMY_PATH = os.path.join(PROJECT_ROOT, "config", "vulnerability_taxonomy.json")


class CoverageTracker:
    def __init__(self):
        self.categories = self._load_taxonomy()
        category_status = {cat["id"]: "not_tested" for cat in self.categories}
        target_app = get_target_app()
        objective_status = {
            target_app: {objective: "not_tested" for objective in get_target_objectives(target_app)}
        }
        self.status: Dict[str, dict] = {
            "categories": category_status,
            "objectives": objective_status,
        }

    def _load_taxonomy(self) -> List[dict]:
        try:
            with open(TAXONOMY_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("categories", [])
        except Exception as e:
            print(f"[CoverageTracker] Failed to load taxonomy: {e}")
            return []

    def _normalize_loaded_status(self) -> None:
        """Handle older flat coverage files without losing compatibility."""
        if not isinstance(self.status, dict):
            self.status = {"categories": {}, "objectives": {}}

        if "categories" not in self.status and any(cat["id"] in self.status for cat in self.categories):
            legacy = dict(self.status)
            fresh_categories = {cat["id"]: "not_tested" for cat in self.categories}
            self.status = {
                "categories": legacy if os.getenv("PRESERVE_LEGACY_COVERAGE", "0") == "1" else fresh_categories,
                "objectives": {},
            }

        self.status.setdefault("categories", {})
        self.status.setdefault("objectives", {})

        for category in self.categories:
            self.status["categories"].setdefault(category["id"], "not_tested")

        target_app = get_target_app()
        self.status["objectives"].setdefault(target_app, {})
        for objective in get_target_objectives(target_app):
            self.status["objectives"][target_app].setdefault(objective, "not_tested")

    @staticmethod
    def _merge_status(existing: str, outcome: str) -> str:
        if existing == "vulnerable":
            return existing
        if outcome == "FULL_LEAK":
            return "vulnerable"
        if outcome == "PARTIAL_LEAK":
            return "in_progress"
        if outcome in {"BLOCKED", "DEFLECTED"}:
            return existing if existing == "in_progress" else "blocked"
        if outcome in {"ERROR", "TIMEOUT_INCONCLUSIVE"}:
            return existing if existing != "not_tested" else "inconclusive"
        return existing

    def update_from_feedback(self, feedback_summary: dict):
        """Update category and objective status based on one round of feedback."""
        self._normalize_loaded_status()
        results = feedback_summary.get("results", []) if isinstance(feedback_summary, dict) else []
        target_app = feedback_summary.get("target_app") or get_target_app()
        self.status["objectives"].setdefault(target_app, {})

        for objective in get_target_objectives(target_app):
            self.status["objectives"][target_app].setdefault(objective, "not_tested")

        for item in results:
            if not isinstance(item, dict):
                continue
            outcome = str(item.get("outcome", "ERROR"))
            category = item.get("category")
            objective = item.get("objective")

            if category in self.status["categories"]:
                current = self.status["categories"][category]
                self.status["categories"][category] = self._merge_status(current, outcome)

            if objective:
                current = self.status["objectives"][target_app].get(objective, "not_tested")
                self.status["objectives"][target_app][objective] = self._merge_status(current, outcome)

    def get_summary(self) -> dict:
        """Return category and target-objective coverage summary."""
        self._normalize_loaded_status()
        target_app = get_target_app()
        category_status = self.status["categories"]
        objective_status = self.status["objectives"].get(target_app, {})

        return {
            "target_app": target_app,
            "category_status": category_status,
            "objective_status": objective_status,
            "untested_categories": [cat for cat, stat in category_status.items() if stat == "not_tested"],
            "vulnerable_categories": [cat for cat, stat in category_status.items() if stat == "vulnerable"],
            "untested_objectives": [obj for obj, stat in objective_status.items() if stat == "not_tested"],
            "vulnerable_objectives": [obj for obj, stat in objective_status.items() if stat == "vulnerable"],
        }
