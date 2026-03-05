# llm_client.py
from __future__ import annotations

from typing import Any, Dict, Optional

import requests


class LocalOpenAIClient:
    """
    Minimal OpenAI-compatible chat client for local servers like LM Studio.

    Typical LM Studio server:
      base_url = "http://localhost:1234/v1"
      api_key  = "lm-studio" (LM Studio ignores this but expects a Bearer token format)
      model    = "google_gemma-3-1b-it"
    """

    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    def chat(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.2,
        max_tokens: int = 256,
    ) -> str:
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload: Dict[str, Any] = {
            "model": self.model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }

        resp = requests.post(url, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]