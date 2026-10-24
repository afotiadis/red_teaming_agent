import os
import unittest
from unittest.mock import patch

from src.target_profiles import (
    build_target_headers,
    build_target_payload,
    get_target_app,
    get_target_attack_strategy,
    get_target_chat_url,
    get_target_description,
    get_target_health_url,
    get_target_profile,
    target_auth_is_required,
)


TARGET_ENV_KEYS = {
    "TARGET_APP", "TARGET_BASE_URL", "TARGET_CHAT_URL", "TARGET_HEALTH_URL",
    "TARGET_REQUEST_FORMAT", "TARGET_REQUEST_FIELD", "TARGET_AUTH_MODE",
    "TARGET_AUTH_REQUIRED", "TARGET_AUTH_HEADER", "TARGET_AUTH_TOKEN",
    "ZERO_HEALTH_JWT", "VULN_BANK_JWT",
}


class TargetProfileTests(unittest.TestCase):
    def target_env(self, **values):
        clean_env = {key: value for key, value in os.environ.items() if key not in TARGET_ENV_KEYS}
        clean_env.update(values)
        return patch.dict(os.environ, clean_env, clear=True)

    def test_all_validation_application_contracts(self):
        expected = {
            "zero_health": ("/api/chatbot/chat", "/api/health", "message", "zero_health", True),
            "dvaia": ("/api/agent/chat", "/api/health", "prompt", "dvaia", False),
            "vuln_bank": ("/api/ai/chat", "/healthz", "message", "vuln_bank", True),
            "vulnerable_chat": ("/api/chat", "/health", "message", "vulnerable_chat", False),
        }

        for app, (chat_path, health_path, field, strategy, auth_required) in expected.items():
            with self.subTest(app=app), self.target_env(TARGET_APP=app):
                self.assertTrue(get_target_chat_url().endswith(chat_path))
                self.assertTrue(get_target_health_url().endswith(health_path))
                self.assertEqual(build_target_payload("probe"), {field: "probe"})
                self.assertEqual(get_target_attack_strategy(), strategy)
                self.assertEqual(target_auth_is_required(), auth_required)
                self.assertTrue(get_target_description())

    def test_base_url_changes_host_without_changing_profile_paths(self):
        with self.target_env(TARGET_APP="dvaia", TARGET_BASE_URL="http://127.0.0.1:5100/"):
            self.assertEqual(get_target_chat_url(), "http://127.0.0.1:5100/api/agent/chat")
            self.assertEqual(get_target_health_url(), "http://127.0.0.1:5100/api/health")

    def test_specific_urls_override_profile_urls(self):
        with self.target_env(
            TARGET_APP="vulnerable_chat",
            TARGET_CHAT_URL="https://target.example/custom/chat/",
            TARGET_HEALTH_URL="https://target.example/status/",
        ):
            self.assertEqual(get_target_chat_url(), "https://target.example/custom/chat")
            self.assertEqual(get_target_health_url(), "https://target.example/status")

    def test_repository_name_alias_and_bearer_token(self):
        with self.target_env(TARGET_APP="vuln-bank", VULN_BANK_JWT="bank-token"):
            self.assertEqual(get_target_app(), "vuln_bank")
            self.assertEqual(build_target_headers(), {"Authorization": "Bearer bank-token"})

    def test_unknown_profile_fails_instead_of_silently_using_generic(self):
        with self.target_env(TARGET_APP="typo"):
            with self.assertRaisesRegex(ValueError, "Unknown TARGET_APP"):
                get_target_profile()


if __name__ == "__main__":
    unittest.main()
