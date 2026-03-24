import os
import requests
from typing import Any, Dict, List, Optional, Union
from crewai import BaseLLM

class AriadneLLM(BaseLLM):
    """Native Custom LLM wrapper using ReAct prompting for CrewAI."""
    
    def __init__(self, model: str = "claude-sonnet-4", temperature: Optional[float] = 0.7, **kwargs):
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
        
        if isinstance(messages, str):
            messages = [{"role": "user", "content": messages}]
            
        headers = {"Authorization": f"Bearer {self.api_token}"}
        
        # In ReAct mode, CrewAI injects tool descriptions directly into the text messages.
        # We no longer need to translate or pass a "tools" array to the API!
        payload = {
            "provider": self.provider,
            "model": self.model,
            "messages": messages,
            "max_tokens": 4096,
            "temperature": self.temperature
        }
        
        response = requests.post(f"{self.base_url}/v1/messages", headers=headers, json=payload)
        
        if response.status_code != 200:
            raise Exception(f"[ARIADNE_WRAPPER_ERROR] {response.status_code}: {response.text}")
            
        data = response.json()
        
        full_text = ""
        for item in data.get("content", []):
            if item.get("type") == "text":
                full_text += item["text"]

        # CRUCIAL FOR REACT: CrewAI passes stop words like "\nObservation:" to halt the LLM 
        # so CrewAI can execute the tool. We manually truncate the output here.
        stop_words = kwargs.get("stop", [])
        if stop_words:
            for stop_word in stop_words:
                if stop_word in full_text:
                    full_text = full_text.split(stop_word)[0]
                    break
                    
        return full_text

    def supports_function_calling(self) -> bool:
        # FALSE forces CrewAI to take over and execute the tools natively via ReAct prompting
        return False
        
    def supports_stop_words(self) -> bool:
        # FALSE tells CrewAI we are manually handling stop words in the call() method
        return False