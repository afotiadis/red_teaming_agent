"""Environment-driven target profiles for the red-teaming workflow.

Each profile describes the HTTP contract of one supported validation target.
Operators normally select a profile with ``TARGET_APP`` and only set
``TARGET_BASE_URL`` when the application is not running at its local default.
The more specific URL, payload, and authentication variables remain available
as overrides for custom deployments.
"""

from __future__ import annotations

import os
from urllib.parse import urljoin


TARGET_PROFILES = {
    "generic": {
        "description": "Bundled vulnerable IT-support agentic chatbot",
        "base_url": "http://127.0.0.1:8000",
        "chat_path": "/chat",
        "health_path": "/health",
        "history_path": "/history",
        "enhanced_chat_path": "/enhanced-chat",
        "request_format": "json_message",
        "request_field": "message",
        "auth_mode": "none",
        "auth_required": False,
        "auth_header": "Authorization",
        "attack_strategy": "local_fast",
    },
    "zero_health": {
        "description": "Zero-Health authenticated medical-assistant chatbot",
        "base_url": "http://localhost:5000",
        "chat_path": "/api/chatbot/chat",
        "health_path": "/api/health",
        "history_path": "/api/chatbot/history",
        "enhanced_chat_path": "/api/chatbot/enhanced-chat",
        "request_format": "json_message",
        "request_field": "message",
        "auth_mode": "bearer",
        "auth_required": True,
        "auth_header": "Authorization",
        "attack_strategy": "zero_health",
    },
    "dvaia": {
        "description": "DVAIA ReAct agent with intentionally vulnerable tools",
        "base_url": "http://localhost:5000",
        # DVAIA also has /api/chat. The agent endpoint is the relevant default
        # for evaluating an agentic red-teaming framework.
        "chat_path": "/api/agent/chat",
        "health_path": "/api/health",
        "history_path": None,
        "enhanced_chat_path": "/api/chat-with-template",
        "request_format": "json_prompt",
        "request_field": "prompt",
        "auth_mode": "none",
        "auth_required": False,
        "auth_header": "Authorization",
        "attack_strategy": "dvaia",
    },
    "vuln_bank": {
        "description": "Vuln-Bank authenticated AI customer-support agent with account context",
        "base_url": "http://localhost:5000",
        # The authenticated route includes account context and therefore
        # exercises the bank agent's authorization and excessive-agency risks.
        "chat_path": "/api/ai/chat",
        "health_path": "/healthz",
        "history_path": None,
        "enhanced_chat_path": "/api/ai/chat/anonymous",
        "request_format": "json_message",
        "request_field": "message",
        "auth_mode": "bearer",
        "auth_required": True,
        "auth_header": "Authorization",
        "attack_strategy": "vuln_bank",
    },
    "vulnerable_chat": {
        "description": "Vulnerable Chat intentionally insecure banking chatbot",
        "base_url": "http://localhost:5000",
        "chat_path": "/api/chat",
        "health_path": "/health",
        "history_path": None,
        "enhanced_chat_path": None,
        "request_format": "json_message",
        "request_field": "message",
        "auth_mode": "none",
        "auth_required": False,
        "auth_header": "Authorization",
        "attack_strategy": "vulnerable_chat",
    },
}

TARGET_ALIASES = {
    "zero-health": "zero_health",
    "zerohealth": "zero_health",
    "dvaia-damn-vulnerable-ai-application": "dvaia",
    "dvaia_damn_vulnerable_ai_application": "dvaia",
    "vuln-bank": "vuln_bank",
    "vulnbank": "vuln_bank",
    "vulnerable-chat": "vulnerable_chat",
    "vulnerablechat": "vulnerable_chat",
}


def _clean_url(url: str) -> str:
    return url.strip().rstrip("/")


def _profile_url(path_key: str) -> str | None:
    path = get_target_profile().get(path_key)
    if not path:
        return None
    return urljoin(f"{get_target_base_url()}/", str(path).lstrip("/"))


def get_target_app() -> str:
    configured = os.getenv("TARGET_APP", "generic").strip().lower() or "generic"
    return TARGET_ALIASES.get(configured, configured)


def get_target_profile() -> dict:
    target_app = get_target_app()
    if target_app not in TARGET_PROFILES:
        choices = ", ".join(TARGET_PROFILES)
        raise ValueError(f"Unknown TARGET_APP '{target_app}'. Supported values: {choices}")
    return TARGET_PROFILES[target_app]


def get_target_base_url() -> str:
    return _clean_url(os.getenv("TARGET_BASE_URL", get_target_profile()["base_url"]))


def get_target_chat_url() -> str:
    configured = os.getenv("TARGET_CHAT_URL")
    return _clean_url(configured) if configured else _profile_url("chat_path") or get_target_base_url()


def get_target_health_url() -> str:
    configured = os.getenv("TARGET_HEALTH_URL")
    if configured:
        return _clean_url(configured)
    return _profile_url("health_path") or f"{get_target_base_url()}/health"


def get_target_history_url() -> str:
    configured = os.getenv("TARGET_HISTORY_URL")
    if configured:
        return _clean_url(configured)
    return _profile_url("history_path") or f"{get_target_base_url()}/history"


def get_target_enhanced_chat_url() -> str:
    configured = os.getenv("TARGET_ENHANCED_CHAT_URL")
    if configured:
        return _clean_url(configured)
    return _profile_url("enhanced_chat_path") or get_target_chat_url()


def get_target_request_format() -> str:
    return os.getenv("TARGET_REQUEST_FORMAT", get_target_profile()["request_format"]).strip().lower()


def get_target_request_field() -> str:
    return os.getenv("TARGET_REQUEST_FIELD", get_target_profile()["request_field"]).strip()


def get_target_auth_mode() -> str:
    return os.getenv("TARGET_AUTH_MODE", get_target_profile()["auth_mode"]).strip().lower()


def target_auth_is_required() -> bool:
    override = os.getenv("TARGET_AUTH_REQUIRED")
    if override is not None:
        return override.strip().lower() in {"1", "true", "yes", "on"}
    return bool(get_target_profile().get("auth_required"))


def get_target_auth_token() -> str:
    """Return only target-side credentials, never the red-team LLM API key."""
    return (
        os.getenv("TARGET_AUTH_TOKEN")
        or os.getenv("ZERO_HEALTH_JWT")
        or os.getenv("VULN_BANK_JWT")
        or ""
    ).strip()


def get_target_attack_strategy() -> str:
    return str(get_target_profile().get("attack_strategy", "local_fast"))


def get_target_description() -> str:
    return str(get_target_profile().get("description", get_target_app()))


def build_target_headers(extra_headers: dict | None = None) -> dict:
    headers: dict[str, str] = {}
    auth_mode = get_target_auth_mode()
    token = get_target_auth_token()
    auth_header = os.getenv("TARGET_AUTH_HEADER", get_target_profile()["auth_header"]).strip()

    if auth_mode in {"bearer", "bearer_jwt"} and token:
        headers[auth_header] = f"Bearer {token}"
    elif auth_mode == "api_key" and token:
        headers[auth_header] = token

    if extra_headers:
        headers.update(extra_headers)
    return headers


def build_target_payload(prompt: str) -> object:
    if get_target_request_format() == "plain_text":
        return prompt
    return {get_target_request_field(): prompt}
