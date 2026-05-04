"""
Ariadne LLM Wrapper for CrewAI

This module provides a custom LLM implementation that integrates the Ariadne API
with the CrewAI framework. It handles:
- Authentication via bearer token
- Message formatting and routing
- CrewAI-specific requirements (function calling disabled, stop word handling)
- ReAct prompt termination to allow tool execution
- Debug output for monitoring LLM calls

The wrapper is designed to work with Claude models via the Ariadne API while
maintaining compatibility with CrewAI's agent orchestration system.
"""

import os
import requests
from typing import Any, Dict, List, Optional, Union
from crewai import BaseLLM

class AriadneLLM(BaseLLM):
    """
    Native Custom LLM wrapper for Ariadne API integration with CrewAI.
    
    This class extends BaseLLM to provide:
    - Direct HTTP calls to the Ariadne API (https://ariadne.issel.ee.auth.gr/api)
    - Message formatting with system prompt extraction
    - ReAct stop word handling to prevent hallucination
    - CrewAI compatibility by disabling native function calling
    
    Configuration:
    - ARIADNE_API_TOKEN: Bearer token for authentication (required)
    - Model: Claude Haiku 4.5 (or other Claude variants)
    - Temperature: Controls output randomness (0.7 default)
    - max_tokens: Max completion length (4096)
    
    Usage:
        llm = AriadneLLM()
        response = llm.call("What is 2+2?")
    """
    
    def __init__(self, model: str = "claude-haiku-4-5@20251001", temperature: Optional[float] = 0.7, **kwargs):
        """
        Initialize the Ariadne LLM wrapper.
        
        Args:
            model: Claude model identifier (default: claude-haiku-4-5@20251001)
                   Other options: claude-sonnet-4, claude-opus, etc.
            temperature: Sampling temperature between 0 and 1 (default: 0.7)
                        0.0 = deterministic, 1.0 = maximum randomness
            **kwargs: Additional arguments passed to BaseLLM
        
        Raises:
            RuntimeError: Will be raised during call() if ARIADNE_API_TOKEN is not set
        """
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
        """
        Execute a call to the Ariadne Claude API.
        
        This method:
        1. Validates the API token is configured
        2. Converts string messages to proper message format
        3. Extracts system prompts from message list
        4. Builds the API payload with proper structure
        5. Sends HTTP POST request to Ariadne API
        6. Parses JSON response and extracts text content
        7. Handles CrewAI ReAct stop words to trigger tool execution
        
        Args:
            messages: Either a string prompt or list of message dicts with 'role' and 'content'
                     Message roles: 'system', 'user', 'assistant'
            callbacks: CrewAI callback handlers (unused but required by interface)
            **kwargs: Additional parameters including:
                     - stop: List of stop words to truncate generation
        
        Returns:
            Generated text response from Claude API, with ReAct stop words handled
        
        Raises:
            RuntimeError: If ARIADNE_API_TOKEN environment variable is not set
            Exception: If API call returns non-200 status code
        """

        if not self.api_token:
            raise RuntimeError("ARIADNE_API_TOKEN is not set. Export it before running the crew.")
        
        # Convert string input to proper message format
        if isinstance(messages, str):
            messages = [{"role": "user", "content": messages}]
            
        # Set authorization header
        headers = {"Authorization": f"Bearer {self.api_token}"}
        
        # 1. Extract the system prompt from the messages list
        # System prompts are stored separately in the Ariadne payload
        system_prompt = ""
        filtered_messages = []
        for msg in messages:
            if msg.get("role") == "system":
                system_prompt += msg.get("content", "") + "\n"
            else:
                filtered_messages.append(msg)
        
        # 2. Build the payload according to Ariadne API specification
        payload = {
            "provider": self.provider,
            "model": self.model,  # e.g., "claude-haiku-4-5@20251001"
            "messages": filtered_messages,
            "max_tokens": 4096,  # Maximum output tokens
            "temperature": self.temperature  # Sampling temperature
        }
        
        # 3. Inject system prompt at top level if present
        if system_prompt:
            payload["system"] = system_prompt.strip()
            
        # Make HTTP request to Ariadne API
        response = requests.post(f"{self.base_url}/v1/messages", headers=headers, json=payload, timeout=120)
        
        # Check for API errors
        if response.status_code != 200:
            raise Exception(f"[ARIADNE_WRAPPER_ERROR] {response.status_code}: {response.text}")
            
        # Parse response and extract text content
        data = response.json()
        
        full_text = ""
        for item in data.get("content", []):
            if item.get("type") == "text":
                full_text += item["text"]

        # Debug output showing raw LLM response
        print(f"\n{'='*20} 🕵️‍♂️ RAW LLM OUTPUT {'='*20}")
        print(full_text)
        print(f"{'='*60}\n")

        # 4. Handle CrewAI's stop words to yield execution back to Python
        # Prevents the LLM from trying to predict tool responses
        stop_words = kwargs.get("stop", [])
        if stop_words:
            for stop_word in stop_words:
                if stop_word in full_text:
                    full_text = full_text.split(stop_word)[0]
                    break
                    
        # 5. Hardcoded failsafe for ReAct: cut off at "Observation:" to allow tool execution
        # This ensures CrewAI takes back control and runs tools rather than the LLM
        # hallucinating observations
        failsafe_stops = ["\nObservation:", "Observation:", "Observation ", "\nObservation "]
        for stop in failsafe_stops:
            if stop in full_text:
                full_text = full_text.split(stop)[0]
                # Append the stop word back so CrewAI's parser recognizes proper termination
                full_text += f"\n{stop.strip()}" 
                break
            
        return full_text

    def supports_function_calling(self) -> bool:
        """
        Indicate whether this LLM supports native function calling.
        
        Returns False to force CrewAI to handle tool calling via ReAct prompting.
        This ensures tool execution is controlled by CrewAI's agent framework
        rather than relying on Claude's native tool use capability.
        
        Returns:
            False: Disable native function calling, use ReAct instead
        """
        return False
        
    def supports_stop_words(self) -> bool:
        """
        Indicate whether this LLM supports native stop word handling.
        
        Returns False because we handle stop words manually in the call() method.
        This gives us fine-grained control over ReAct termination and ensures
        proper tool execution triggering.
        
        Returns:
            False: Disable native stop word handling, manage manually
        """
        return False