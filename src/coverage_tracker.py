"""Module for tracking vulnerability coverage across attack rounds."""

import json
import os
from typing import Dict, List

TAXONOMY_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 
    "config", 
    "vulnerability_taxonomy.json"
)

class CoverageTracker:
    def __init__(self):
        self.categories = self._load_taxonomy()
        # Track status per category: "not_tested", "in_progress", "blocked", "vulnerable"
        self.status: Dict[str, str] = {cat["id"]: "not_tested" for cat in self.categories}
        
    def _load_taxonomy(self) -> List[dict]:
        try:
            with open(TAXONOMY_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("categories", [])
        except Exception as e:
            print(f"[CoverageTracker] Failed to load taxonomy: {e}")
            return []
            
    def update_from_feedback(self, feedback_summary: dict):
        """Update coverage status based on round feedback."""
        results = feedback_summary.get("results", [])
        
        for item in results:
            # We assume the analyzer or executor associates the prompt with a category.
            # If not explicitly mapped, we heuristic match or leave it generic.
            category = item.get("category", "prompt_injection") # Fallback
            outcome = item.get("outcome")
            
            if category not in self.status:
                continue
                
            if outcome == "FULL_LEAK":
                self.status[category] = "vulnerable"
            elif outcome in ["BLOCKED", "DEFLECTED"] and self.status[category] not in ("vulnerable", "in_progress"):
                self.status[category] = "blocked"
            elif outcome == "PARTIAL_LEAK" and self.status[category] != "vulnerable":
                self.status[category] = "in_progress"

    def get_summary(self) -> dict:
        """Return the current coverage summary."""
        return {
            "status": self.status,
            "untested_categories": [cat for cat, stat in self.status.items() if stat == "not_tested"],
            "vulnerable_categories": [cat for cat, stat in self.status.items() if stat == "vulnerable"]
        }
