"""Module for managing experiential memory of the planner.

The memory store allows the planner to track which attack vectors succeed against
which types of targets across multiple runs, improving future planning.
"""

import os
import json
from pathlib import Path

MEMORY_LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 
    "data", 
    "experiential_memory", 
    "log.md"
)

class ExperientialMemory:
    @staticmethod
    def log_success(target_desc: str, vulnerability: str, payload: str, note: str):
        """Append a successful attack vector to the experiential memory log."""
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(MEMORY_LOG_PATH), exist_ok=True)
        
        entry = f"""
## Entry - Target: {target_desc[:50]}...
- **Vulnerability**: {vulnerability}
- **Successful Payload**: `{payload}`
- **Note**: {note}
"""
        try:
            with open(MEMORY_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(entry)
        except Exception as e:
            print(f"[Memory] Failed to write memory log: {e}")

    @staticmethod
    def extract_and_store_from_feedback(target_desc: str, feedback_summary: dict):
        """Extract successful attacks from a feedback summary and log them."""
        results = feedback_summary.get("results", [])
        
        for item in results:
            if item.get("outcome") == "FULL_LEAK":
                payload = item.get("prompt", "")
                ExperientialMemory.log_success(
                    target_desc=target_desc,
                    vulnerability="Unknown (Auto-extracted)",
                    payload=payload,
                    note="Automatically extracted from a successful multi-turn loop round."
                )
