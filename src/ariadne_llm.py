import os
import requests
from typing import Any, Dict, List, Optional, Union
from crewai import BaseLLM

class AriadneLLM(BaseLLM):
    """Native Custom LLM wrapper using ReAct prompting for CrewAI."""
    
    def __init__(self, model: str = "claude-sonnet-4-6", temperature: Optional[float] = 0.7, **kwargs):
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

        if not self.api_token:
            raise RuntimeError("ARIADNE_API_TOKEN is not set. Export it before running the crew.")
        
        if isinstance(messages, str):
            messages = [{"role": "user", "content": messages}]
            
        headers = {"Authorization": f"Bearer {self.api_token}"}
        
        # 1. Extract the system prompt from the messages list
        system_prompt = ""
        filtered_messages = []
        for msg in messages:
            if msg.get("role") == "system":
                system_prompt += msg.get("content", "") + "\n"
            else:
                filtered_messages.append(msg)
        
        # 2. Build the correct payload based on the docs
        payload = {
            "provider": self.provider,
            "model": self.model, # claude-sonnet-4-6 [cite: 56]
            "messages": filtered_messages,
            "max_tokens": 4096, # [cite: 63]
            "temperature": self.temperature # [cite: 61]
        }
        
        # 3. Inject it at the top level 
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

        # 👇 ADD THESE DEBUG PRINTS 👇
        print(f"\n{'='*20} 🕵️‍♂️ RAW LLM OUTPUT {'='*20}")
        print(full_text)
        print(f"{'='*60}\n")

        # 4. Handle CrewAI's stop words to yield execution back to Python
        stop_words = kwargs.get("stop", [])
        if stop_words:
            for stop_word in stop_words:
                if stop_word in full_text:
                    full_text = full_text.split(stop_word)[0]
                    break
                    
        # 2. Hardcode a failsafe truncation for ReAct
        # If Claude tries to write "Observation:", we cut it off immediately.
        # This forces CrewAI to take back control and run the tool.
        failsafe_stops = ["\nObservation:", "Observation:", "Observation ", "\nObservation "]
        for stop in failsafe_stops:
            if stop in full_text:
                full_text = full_text.split(stop)[0]
                # We append the stop word back on so CrewAI's parser knows it stopped correctly
                full_text += f"\n{stop.strip()}" 
                break
            
        return full_text

    def supports_function_calling(self) -> bool:
        # FALSE forces CrewAI to take over and execute the tools natively via ReAct prompting
        return False
        
    def supports_stop_words(self) -> bool:
        # FALSE tells CrewAI we are manually handling stop words in the call() method
        return False