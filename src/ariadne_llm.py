"""Custom CrewAI LLM adapter for the Ariadne API.

CrewAI expects a provider object that can accept chat messages and return the
next assistant response. Ariadne uses its own message schema, so this wrapper
translates between the two formats and keeps the rest of the project unaware of
the API-specific details.

The adapter also separates the system prompt from the conversation history and
applies a stop-word strategy so CrewAI can take back control when the model is
expected to yield to tool execution.
"""

import os
import requests
from typing import Any, Dict, List, Optional, Union
from crewai import BaseLLM

class AriadneLLM(BaseLLM):
    """CrewAI-compatible wrapper around Ariadne's chat completion endpoint."""
    
    def __init__(self, model: str = "claude-haiku-4-5@20251001", temperature: Optional[float] = 0.7, **kwargs):
        """Store the connection settings and model defaults used for each call."""
        super().__init__(model=model, temperature=temperature, **kwargs)
        self.api_token = os.getenv("ARIADNE_API_TOKEN", "")
        self.base_url = "https://ariadne.issel.ee.auth.gr/api"
        self.provider = "gcp"

    def call(
        self,
        messages: Union[str, List[Dict[str, str]]],
        callbacks: Optional[List[Any]] = None,
        **kwargs: Any,
    ) -> str:
        """Send a normalized prompt to Ariadne and return the assistant text.

        The method performs four jobs in order:
        1. Normalize CrewAI's input into a message list.
        2. Split out any system prompt and preserve it separately.
        3. Call Ariadne's messages endpoint and collect the text response.
        4. Trim the text at CrewAI stop words so tool execution can resume.
        """

        if not self.api_token:
            raise RuntimeError("ARIADNE_API_TOKEN is not set. Export it before running the crew.")
        
        if isinstance(messages, str):
            messages = [{"role": "user", "content": messages}]
            
        headers = {"Authorization": f"Bearer {self.api_token}"}
        
        # Ariadne expects the system prompt separately from the message list.
        system_prompt = ""
        filtered_messages = []
        for msg in messages:
            if msg.get("role") == "system":
                system_prompt += msg.get("content", "") + "\n"
            else:
                filtered_messages.append(msg)
        
        # Build the payload shape required by Ariadne's `/v1/messages` endpoint.
        payload = {
            "provider": self.provider,
            "model": self.model,
            "messages": filtered_messages,
            "max_tokens": 4096,
            "temperature": self.temperature,
        }
        
        # Keep the system instructions at the top level where Ariadne expects them.
        if system_prompt:
            payload["system"] = system_prompt.strip()
            
        response = requests.post(f"{self.base_url}/v1/messages", headers=headers, json=payload, timeout=120)
        
        if response.status_code != 200:
            raise Exception(f"[ARIADNE_WRAPPER_ERROR] {response.status_code}: {response.text}")
            
        data = response.json()
        
        full_text = ""
        for item in data.get("content", []):
            if item.get("type") == "text":
                full_text += item["text"]

        # Emit the raw model output so the crew logs show exactly what came back.
        print(f"\n{'='*20} 🕵️‍♂️ RAW LLM OUTPUT {'='*20}")
        print(full_text)
        print(f"{'='*60}\n")

        # Respect any explicit CrewAI stop words first.
        stop_words = kwargs.get("stop", [])
        if stop_words:
            for stop_word in stop_words:
                if stop_word in full_text:
                    full_text = full_text.split(stop_word)[0]
                    break
                    
        # Failsafe for ReAct-style output: if the model starts writing an observation,
        # stop there so CrewAI can perform the tool call instead of the model narrating it.
        failsafe_stops = ["\nObservation:", "Observation:", "Observation ", "\nObservation "]
        for stop in failsafe_stops:
            if stop in full_text:
                full_text = full_text.split(stop)[0]
                # Re-attach the marker so CrewAI can still detect the stopping point.
                full_text += f"\n{stop.strip()}" 
                break
            
        return full_text

    def supports_function_calling(self) -> bool:
        """Tell CrewAI that tool execution is handled by the agent loop, not the provider."""
        return False
        
    def supports_stop_words(self) -> bool:
        """Tell CrewAI that stop-word handling is implemented manually in ``call()``."""
        return False