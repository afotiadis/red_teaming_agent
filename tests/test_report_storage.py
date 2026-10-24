import os
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("SKIP_RAG_INIT", "1")
os.environ.setdefault("OPENROUTER_API_KEY", "test-key")

import main


class ReportStorageTests(unittest.TestCase):
    @staticmethod
    def _fake_pdf(html_content, dest):
        dest.write(b"%PDF-1.4\n% test report\n")
        return SimpleNamespace(err=0)

    @patch("main.pisa.CreatePDF", side_effect=_fake_pdf.__func__)
    def test_pdf_reports_are_unique_and_do_not_overwrite(self, _create_pdf):
        with tempfile.TemporaryDirectory() as temp_dir:
            first_path = main.save_report("# First run", output_dir=temp_dir)
            second_path = main.save_report("# Second run", output_dir=temp_dir)

            self.assertNotEqual(first_path, second_path)
            self.assertTrue(first_path.exists())
            self.assertTrue(second_path.exists())
            self.assertEqual(len(list(Path(temp_dir).glob("*.pdf"))), 2)
            self.assertIn("red_team_report_", first_path.name)

    def test_relative_output_directory_is_rooted_at_project(self):
        resolved = main._resolve_report_output_dir("reports/test-archive")
        self.assertEqual(resolved, (main.PROJECT_ROOT / "reports/test-archive").resolve())

    def test_filename_component_is_portable(self):
        self.assertEqual(main._safe_filename_component("Zero Health / Patient"), "zero_health_patient")

    def test_five_round_transcript_contains_all_forty_results(self):
        all_results = []
        for round_number in range(1, 6):
            executor_results = []
            analyzer_results = []
            for prompt_number in range(1, 9):
                executor_results.append({
                    "prompt_index": prompt_number,
                    "prompt": f"round {round_number} prompt {prompt_number}",
                    "status_code": 200,
                    "response": {"response": f"answer {round_number}-{prompt_number}"},
                })
                analyzer_results.append({
                    "outcome": "BLOCKED",
                    "category": "prompt_injection",
                })
            all_results.append({
                "executor_raw": json.dumps({"target": "http://target/chat", "results": executor_results}),
                "analyzer_raw": json.dumps({"results": analyzer_results}),
            })

        transcripts, summary, markers = main.build_report_evidence(all_results)
        narrative = """# Security Report
## 1. Executive Summary
Summary.
## 2. Target Details
Target.
## 3. Attack Methodology and Key Findings
Method.
## 5. Remediation Recommendations
Fixes.
"""
        report = main.assemble_complete_report(narrative, transcripts)
        main.validate_complete_report(report, markers)

        self.assertEqual(summary["rounds_executed"], 5)
        self.assertEqual(summary["total_prompt_results"], 40)
        self.assertEqual(len(markers), 40)
        self.assertIn("answer 5-8", report)
        self.assertTrue(report.rstrip().endswith("<!-- END OF REPORT -->"))

    def test_incomplete_narrative_is_rejected_before_pdf_generation(self):
        narrative = """## 1. Executive Summary
Summary.
## 2. Target Details
Target.
## 3. Attack Methodology and Key Findings
Method.
"""
        with self.assertRaisesRegex(RuntimeError, "Section 5"):
            main.assemble_complete_report(narrative, "transcripts")


if __name__ == "__main__":
    unittest.main()
