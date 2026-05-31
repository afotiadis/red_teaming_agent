"""CrewAI LLM adapter for OpenRouter API.

This wrapper mirrors the interface used by `AriadneLLM` so the rest of the
codebase can remain unchanged. It prefers the `OPENROUTER_API_KEY` environment
variable and exposes the same convenience methods used by the project.
"""

import os
import requests
from typing import Any, Dict, List, Optional, Union
from crewai import BaseLLM


class OpenRouterLLM(BaseLLM):
    """Simple wrapper around OpenRouter's chat completions endpoint.

    Reads configuration from environment variables to enable easy tuning
    without changing code. Designed to be compatible with the project's
    existing `AriadneLLM` interface.
    """

    def __init__(self, model: str | None = None, temperature: Optional[float] = None, **kwargs):
        # Default to the free gpt-oss-120b model recommended by the user.
        default_model = os.getenv("OPENROUTER_MODEL", "openai/gpt-oss-120b:free")
        model = model or default_model
        temperature = temperature if temperature is not None else float(os.getenv("OPENROUTER_TEMPERATURE", "0.7"))
        super().__init__(model=model, temperature=temperature, **kwargs)
        self.api_key = os.getenv("OPENROUTER_API_KEY", "")
        self.base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
        self.max_tokens = int(os.getenv("LLM_MAX_TOKENS", "4096"))
        self.timeout_seconds = int(os.getenv("OPENROUTER_TIMEOUT", "120"))
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

        # The OpenRouter chat endpoint is typically at /chat/completions
        url = f"{self.base_url}/chat/completions"
        response = requests.post(url, headers=headers, json=payload, timeout=self.timeout_seconds)

        if response.status_code != 200:
            raise Exception(f"[OPENROUTER_WRAPPER_ERROR] {response.status_code}: {response.text}")

        data = response.json()

        # Best-effort extraction: support both OpenAI-style and alternate shapes.
        full_text = ""
        try:
            choice = data.get("choices", [])[0]
            if isinstance(choice.get("message"), dict):
                full_text = choice["message"].get("content", "")
            else:
                # Some providers return a string directly
                full_text = choice.get("text", "") or choice.get("message", "")
        except Exception:
            # Last resort: try common fields
            full_text = data.get("generated_text") or data.get("text", "") or ""

        # Respect any explicit CrewAI stop words first.
        stop_words = kwargs.get("stop", [])
        if stop_words:
            for stop_word in stop_words:
                if stop_word in full_text:
                    full_text = full_text.split(stop_word)[0]
                    break

        # Failsafe for ReAct-style output, same as Ariadne wrapper.
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
