"""CrewAI LLM adapter for OpenRouter API.

This wrapper mirrors the interface used by `AriadneLLM` so the rest of the
codebase can remain unchanged. It prefers the `OPENROUTER_API_KEY` environment
variable and exposes the same convenience methods used by the project.
"""

import os
import time
import requests
from typing import Any, Dict, List, Optional, Union
from crewai import BaseLLM


TRANSIENT_OPENROUTER_STATUS_CODES = {404, 408, 409, 429, 500, 502, 503, 504}


def _content_to_text(content: Any) -> str:
    """Normalize OpenRouter/OpenAI content variants into a plain string."""
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        text_parts = []
        for block in content:
            if isinstance(block, str):
                text_parts.append(block)
            elif isinstance(block, dict):
                block_text = block.get("text") or block.get("content")
                if isinstance(block_text, str):
                    text_parts.append(block_text)
        return "".join(text_parts)

    return ""


def _extract_assistant_text(data: Any) -> tuple[str, str]:
    """Extract assistant text and a compact diagnostic from an API response."""
    if not isinstance(data, dict):
        return "", f"response_type={type(data).__name__}"

    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        choice = choices[0] if isinstance(choices[0], dict) else {}
        message = choice.get("message")
        if isinstance(message, dict):
            text = _content_to_text(message.get("content"))
            if not text:
                text = _content_to_text(message.get("refusal"))
        else:
            text = _content_to_text(message)

        if not text:
            text = _content_to_text(choice.get("text"))

        diagnostic = (
            f"finish_reason={choice.get('finish_reason')!r}, "
            f"message_content_type={type(message.get('content')).__name__ if isinstance(message, dict) else type(message).__name__}, "
            f"message_keys={sorted(message.keys()) if isinstance(message, dict) else []}, "
            f"response_model={data.get('model')!r}, provider={data.get('provider')!r}"
        )
        return text, diagnostic

    fallback_text = _content_to_text(data.get("generated_text")) or _content_to_text(data.get("text"))
    return fallback_text, f"response_keys={sorted(data.keys())}"


def _is_reporter_call(kwargs: dict) -> bool:
    """Return True when ordinary report prose must not be parsed as ReAct control text."""
    agent = kwargs.get("from_agent")
    role = getattr(agent, "role", agent if isinstance(agent, str) else "")
    normalized_role = str(role).lower()
    return "report" in normalized_role or "auditor" in normalized_role


class OpenRouterLLM(BaseLLM):
    """Simple wrapper around OpenRouter's chat completions endpoint.

    Reads configuration from environment variables to enable easy tuning
    without changing code. Designed to be compatible with the project's
    existing `AriadneLLM` interface.
    """

    def __init__(self, model: str | None = None, temperature: Optional[float] = None, **kwargs):
        # The free router avoids pinning the default to a free model that may be retired.
        default_model = os.getenv("OPENROUTER_MODEL", "openrouter/free")
        model = model or default_model
        temperature = temperature if temperature is not None else float(os.getenv("OPENROUTER_TEMPERATURE", "0.7"))
        super().__init__(model=model, temperature=temperature, **kwargs)
        self.api_key = os.getenv("OPENROUTER_API_KEY", "")
        self.base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
        self.max_tokens = int(os.getenv("LLM_MAX_TOKENS", "4096"))
        self.timeout_seconds = int(os.getenv("OPENROUTER_TIMEOUT", "120"))
        self.max_retries = int(os.getenv("OPENROUTER_MAX_RETRIES", "2"))
        self.retry_backoff = float(os.getenv("OPENROUTER_RETRY_BACKOFF", "2"))
        fallback_models_text = os.getenv(
            "OPENROUTER_FALLBACK_MODELS",
            "openrouter/free",
        )
        self.fallback_models = [
            fallback.strip()
            for fallback in fallback_models_text.split(",")
            if fallback.strip() and fallback.strip() != self.model
        ]
        # Optional headers to help OpenRouter attribute traffic to your app
        self.http_referer = os.getenv("OPENROUTER_HTTP_REFERER")
        self.x_title = os.getenv("OPENROUTER_X_TITLE")
        # Reasoning parameters (models like gpt-oss support configurable reasoning)
        self.reasoning_enabled = os.getenv("OPENROUTER_REASONING_ENABLED", "false").lower() == "true"
        self.reasoning_effort = os.getenv("OPENROUTER_REASONING_EFFORT")  # e.g. "low", "medium", "high"
        self.reasoning_max_tokens = os.getenv("OPENROUTER_REASONING_MAX_TOKENS")

    def call(
        self,
        messages: Union[str, List[Dict[str, str]]],
        callbacks: Optional[List[Any]] = None,
        **kwargs: Any,
    ) -> str:
        """Send messages to OpenRouter and return the assistant content.

        Accepts either a single string or a list of message dicts matching the
        CrewAI format: {"role":"user|assistant|system","content":...}.
        """

        if not self.api_key:
            raise RuntimeError("OPENROUTER_API_KEY is not set. Export it before running the crew.")

        if isinstance(messages, str):
            messages = [{"role": "user", "content": messages}]

        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        if self.http_referer:
            headers["HTTP-Referer"] = self.http_referer
        if self.x_title:
            headers["X-Title"] = self.x_title

        # Keep system messages at the top of the message stream for compatibility.
        system_prompt = ""
        filtered_messages = []
        for msg in messages:
            if msg.get("role") == "system":
                system_prompt += msg.get("content", "") + "\n"
            else:
                filtered_messages.append(msg)

        if system_prompt:
            filtered_messages.insert(0, {"role": "system", "content": system_prompt.strip()})

        payload = {
            "model": self.model,
            "messages": filtered_messages,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }

        # Include reasoning configuration when enabled for supported models.
        if self.reasoning_enabled:
            reasoning = {}
            if self.reasoning_effort:
                reasoning["effort"] = self.reasoning_effort
            if self.reasoning_max_tokens:
                try:
                    reasoning["max_tokens"] = int(self.reasoning_max_tokens)
                except Exception:
                    pass
            if reasoning:
                payload["reasoning"] = reasoning

        # Free providers occasionally return a successful envelope with null
        # message content, so retry both transient HTTP failures and empty text.
        url = f"{self.base_url}/chat/completions"
        full_text = ""
        last_error = "unknown OpenRouter response"
        total_attempts = self.max_retries + 1
        model_sequence = [self.model, *self.fallback_models]
        if len(model_sequence) < total_attempts:
            model_sequence.extend([model_sequence[-1]] * (total_attempts - len(model_sequence)))
        model_sequence = model_sequence[:total_attempts]
        attempted_models = []

        for attempt_index in range(total_attempts):
            attempt_number = attempt_index + 1
            attempt_model = model_sequence[attempt_index]
            attempted_models.append(attempt_model)
            attempt_payload = {**payload, "model": attempt_model}
            try:
                response = requests.post(
                    url,
                    headers=headers,
                    json=attempt_payload,
                    timeout=self.timeout_seconds,
                )
            except requests.RequestException as exc:
                last_error = f"request_error={exc}"
                if attempt_index < self.max_retries:
                    time.sleep(self.retry_backoff * (2 ** attempt_index))
                    continue
                raise RuntimeError(
                    f"[OPENROUTER_WRAPPER_ERROR] Request failed after {total_attempts} attempts: {exc}"
                ) from exc

            if response.status_code != 200:
                last_error = f"status={response.status_code}, body={response.text[:500]}"
                if response.status_code in TRANSIENT_OPENROUTER_STATUS_CODES and attempt_index < self.max_retries:
                    time.sleep(self.retry_backoff * (2 ** attempt_index))
                    continue
                raise RuntimeError(f"[OPENROUTER_WRAPPER_ERROR] {last_error}")

            try:
                data = response.json()
            except ValueError as exc:
                last_error = f"invalid_json={exc}, body={response.text[:500]}"
                if attempt_index < self.max_retries:
                    time.sleep(self.retry_backoff * (2 ** attempt_index))
                    continue
                raise RuntimeError(
                    f"[OPENROUTER_WRAPPER_ERROR] Invalid JSON after {total_attempts} attempts: {last_error}"
                ) from exc

            full_text, diagnostic = _extract_assistant_text(data)
            if full_text:
                break

            last_error = f"empty_assistant_content, {diagnostic}"
            if attempt_index < self.max_retries:
                print(
                    f"[OpenRouter] Empty assistant content from {attempt_model} on attempt "
                    f"{attempt_number}/{total_attempts}; retrying with {model_sequence[attempt_index + 1]}. "
                    f"{diagnostic}"
                )
                time.sleep(self.retry_backoff * (2 ** attempt_index))

        if not isinstance(full_text, str) or not full_text:
            raise RuntimeError(
                f"[OPENROUTER_WRAPPER_ERROR] No assistant text after {total_attempts} attempts "
                f"using models {attempted_models}: {last_error}"
            )

        # Respect any explicit CrewAI stop words first.
        stop_words = kwargs.get("stop", [])
        if stop_words:
            for stop_word in stop_words:
                if isinstance(stop_word, str) and stop_word in full_text:
                    full_text = full_text.split(stop_word)[0]
                    break

        # Failsafe for ReAct-style output, same as Ariadne wrapper.
        if not _is_reporter_call(kwargs):
            failsafe_stops = ["\nObservation:", "Observation:", "Observation ", "\nObservation "]
            for stop in failsafe_stops:
                if stop in full_text:
                    full_text = full_text.split(stop)[0]
                    full_text += f"\n{stop.strip()}"
                    break

        return full_text

    def supports_function_calling(self) -> bool:
        return False

    def supports_stop_words(self) -> bool:
        return False
