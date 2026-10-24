"""Experiential memory for successful red-team prompts.

Only strongly confirmed findings are stored. This prevents benign prompts or
weak partial disclosures from polluting future planning.
"""

from __future__ import annotations

import json
import os


MEMORY_LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "experiential_memory",
    "log.md",
)


class ExperientialMemory:
    @staticmethod
    def log_success(
        target_desc: str,
        vulnerability: str,
        payload: str,
        note: str,
        *,
        objective: str = "unknown",
        category: str = "unknown",
        evidence_markers: list[str] | None = None,
    ):
        """Append a confirmed attack vector to the experiential memory log."""
        os.makedirs(os.path.dirname(MEMORY_LOG_PATH), exist_ok=True)
        evidence_markers = evidence_markers or []
        metadata = {
            "objective": objective,
            "category": category,
            "evidence_markers": evidence_markers,
        }

        safe_payload = payload.replace("`", "'")
        entry = f"""
## Entry - Target: {target_desc[:80]}...
- **Vulnerability**: {vulnerability}
- **Objective**: {objective}
- **Category**: {category}
- **Evidence Markers**: {", ".join(evidence_markers) if evidence_markers else "confirmed by analyzer"}
- **Successful Payload**: `{safe_payload}`
- **Metadata**: `{json.dumps(metadata, ensure_ascii=False)}`
- **Note**: {note}
"""
        try:
            with open(MEMORY_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(entry)
        except Exception as e:
            print(f"[Memory] Failed to write memory log: {e}")

    @staticmethod
    def extract_and_store_from_feedback(target_desc: str, feedback_summary: dict):
        """Store only high-confidence FULL_LEAK results."""
        results = feedback_summary.get("results", []) if isinstance(feedback_summary, dict) else []

        for item in results:
            if not isinstance(item, dict):
                continue
            if item.get("outcome") != "FULL_LEAK":
                continue

            evidence_markers = item.get("evidence_markers") or []
            if not evidence_markers and float(item.get("score", 0.0) or 0.0) < 0.9:
                continue

            payload = item.get("prompt", "")
            objective = item.get("objective", "unknown")
            category = item.get("category", "unknown")
            ExperientialMemory.log_success(
                target_desc=target_desc,
                vulnerability=f"{objective} ({category})",
                payload=payload,
                note="Automatically extracted from target-specific FULL_LEAK evidence.",
                objective=objective,
                category=category,
                evidence_markers=list(evidence_markers),
            )
