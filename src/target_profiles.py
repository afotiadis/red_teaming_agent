"""Target profile helpers for the red-teaming workflow.

This module centralizes target-specific defaults so the rest of the code can
switch between generic chatbots and Zero-Health with an env var instead of
hard-coding endpoint shapes in multiple places.
"""

from __future__ import annotations

import os
from urllib.parse import urlsplit, urlunsplit


def _strip_trailing_slash(url: str) -> str:
    return url.rstrip("/")


TARGET_PROFILES = {
    "generic": {
        "chat_url": "http://127.0.0.1:8000/chat",
        "health_url": None,
        "history_url": None,
        "enhanced_chat_url": None,
        "request_format": "json_message",
        "request_field": "message",
        "auth_mode": "none",
        "auth_header": "Authorization",
    },
    "zero_health": {
        "chat_url": "http://localhost:5000/api/chatbot/chat",
        "health_url": "http://localhost:5000/api/health",
        "history_url": "http://localhost:5000/api/chatbot/history",
        "enhanced_chat_url": "http://localhost:5000/api/chatbot/enhanced-chat",
        "request_format": "json_message",
        "request_field": "message",
        "auth_mode": "bearer",
        "auth_header": "Authorization",
    },
}


def get_target_app() -> str:
    return os.getenv("TARGET_APP", "generic").strip().lower() or "generic"


def get_target_profile() -> dict:
    return TARGET_PROFILES.get(get_target_app(), TARGET_PROFILES["generic"])


def get_target_chat_url() -> str:
    profile = get_target_profile()
    return _strip_trailing_slash(os.getenv("TARGET_CHAT_URL", profile["chat_url"]))


#altered code - codex suggestion
def get_target_health_url() -> str:
    configured_url = os.getenv("TARGET_HEALTH_URL")
    if configured_url:
        return _strip_trailing_slash(configured_url)

    profile = get_target_profile()
    default_url = profile.get("health_url")
    if default_url:
        return _strip_trailing_slash(default_url)

    chat_url = get_target_chat_url()
    if chat_url.endswith("/chat"):
        return f"{chat_url[:-5]}/health"
    return f"{chat_url}/health"


def get_target_history_url() -> str:
    profile = get_target_profile()
    default_url = profile.get("history_url")
    if default_url:
        return _strip_trailing_slash(os.getenv("TARGET_HISTORY_URL", default_url))
    chat_url = get_target_chat_url()
    if chat_url.endswith("/chat"):
        return f"{chat_url[:-5]}/history"
    return f"{chat_url}/history"


def get_target_enhanced_chat_url() -> str:
    profile = get_target_profile()
    default_url = profile.get("enhanced_chat_url")
    if default_url:
        return _strip_trailing_slash(os.getenv("TARGET_ENHANCED_CHAT_URL", default_url))
    chat_url = get_target_chat_url()
    if chat_url.endswith("/chat"):
        return f"{chat_url[:-5]}/enhanced-chat"
    return f"{chat_url}/enhanced-chat"


def get_target_request_format() -> str:
    profile = get_target_profile()
    return os.getenv("TARGET_REQUEST_FORMAT", profile["request_format"])


def get_target_request_field() -> str:
    profile = get_target_profile()
    return os.getenv("TARGET_REQUEST_FIELD", profile["request_field"])


def get_target_auth_mode() -> str:
    profile = get_target_profile()
    return os.getenv("TARGET_AUTH_MODE", profile["auth_mode"])


def get_target_auth_token() -> str:
    # Accept a couple of aliases for the target JWT only.
    token = os.getenv("TARGET_AUTH_TOKEN") or os.getenv("ZERO_HEALTH_JWT")
    return token or ""


def build_target_headers(extra_headers: dict | None = None) -> dict:
    headers: dict[str, str] = {}
    auth_mode = get_target_auth_mode()
    token = get_target_auth_token()

    if auth_mode in {"bearer", "bearer_jwt"} and token:
        headers["Authorization"] = f"Bearer {token}"
    elif auth_mode == "api_key" and token:
        headers["Authorization"] = token

    if extra_headers:
        headers.update(extra_headers)
    return headers


def build_target_payload(prompt: str) -> object:
    request_format = get_target_request_format()
    request_field = get_target_request_field()

    if request_format == "plain_text":
        return prompt

    return {request_field: prompt}
