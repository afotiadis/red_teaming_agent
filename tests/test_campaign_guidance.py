import os
import unittest
from unittest.mock import patch

from src.campaign_guidance import get_target_dossier, get_target_objectives
from src.coverage_tracker import CoverageTracker


class CampaignGuidanceTests(unittest.TestCase):
    def test_vuln_bank_dossier_has_result_harvesting_objectives(self):
        dossier = get_target_dossier("vuln_bank")

        self.assertIn("account numbers", dossier["valuable_assets"])
        self.assertIn("access_cross_user_record", dossier["objectives"])

    def test_coverage_tracks_target_objectives(self):
        with patch.dict(os.environ, {"TARGET_APP": "vuln_bank"}, clear=False):
            tracker = CoverageTracker()
            tracker.update_from_feedback(
                {
                    "target_app": "vuln_bank",
                    "results": [
                        {
                            "category": "info_disclosure",
                            "objective": "enumerate_database_schema",
                            "outcome": "FULL_LEAK",
                        }
                    ],
                }
            )

            summary = tracker.get_summary()
            self.assertIn("enumerate_database_schema", summary["vulnerable_objectives"])
            self.assertIn("access_cross_user_record", summary["untested_objectives"])

    def test_legacy_flat_coverage_is_not_preserved_by_default(self):
        with patch.dict(os.environ, {"TARGET_APP": "vuln_bank"}, clear=False):
            tracker = CoverageTracker()
            tracker.status = {
                "prompt_injection": "vulnerable",
                "jailbreak": "vulnerable",
                "info_disclosure": "vulnerable",
                "excessive_agency": "vulnerable",
            }

            summary = tracker.get_summary()
            self.assertEqual(summary["category_status"]["prompt_injection"], "not_tested")


if __name__ == "__main__":
    unittest.main()
