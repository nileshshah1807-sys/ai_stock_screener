"""Small resilient client for OpenRouter chat completions."""

from __future__ import annotations

import json
import re
import time
from typing import Any

import requests


class OpenRouterUnavailable(RuntimeError):
    """Raised for transient provider failures that should be retried next run."""


class OpenRouterResponseError(RuntimeError):
    """Raised when a successful provider response cannot be used safely."""


class OpenRouterClient:
    endpoint = "https://openrouter.ai/api/v1/chat/completions"
    transient_statuses = {429, 500, 502, 503, 504}

    def __init__(self, api_key: str, model_name: str, max_retries: int = 2, timeout_seconds: int = 90):
        if not api_key:
            raise ValueError("OPENROUTER_API_KEY is required")
        self.model_name = model_name
        self.max_retries = max_retries
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "X-Title": "AI Stock Screener",
        }

    def analyze_chunk(self, prompt: str) -> dict[str, Any]:
        payload = {
            "model": self.model_name,
            "temperature": 0,
            "max_tokens": 1200,
            "messages": [
                {"role": "system", "content": "Return only a valid JSON object. Do not use Markdown."},
                {"role": "user", "content": prompt},
            ],
        }
        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.post(
                    self.endpoint,
                    headers=self.headers,
                    json=payload,
                    timeout=self.timeout_seconds,
                )
            except requests.Timeout as exc:
                if attempt == self.max_retries:
                    raise OpenRouterUnavailable("OpenRouter request timed out") from exc
                time.sleep(2 ** attempt)
                continue
            except requests.RequestException as exc:
                raise OpenRouterUnavailable(f"OpenRouter request failed: {exc}") from exc

            if response.status_code in self.transient_statuses:
                if attempt == self.max_retries:
                    raise OpenRouterUnavailable(f"OpenRouter returned {response.status_code}")
                time.sleep(2 ** attempt)
                continue
            if response.status_code >= 400:
                raise OpenRouterResponseError(f"OpenRouter returned {response.status_code}: {response.text[:300]}")

            try:
                content = response.json()["choices"][0]["message"]["content"]
                return _parse_json_object(content)
            except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
                raise OpenRouterResponseError("OpenRouter returned invalid JSON content") from exc
        raise OpenRouterUnavailable("OpenRouter retry loop ended unexpectedly")


def _strip_fence(content: str) -> str:
    content = content.strip()
    return re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.IGNORECASE).strip()


def _parse_json_object(content: str) -> dict[str, Any]:
    """Parse a JSON object even when a provider adds harmless surrounding text."""
    cleaned = _strip_fence(content)
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        object_start = cleaned.find("{")
        if object_start < 0:
            raise
        payload, _ = json.JSONDecoder().raw_decode(cleaned[object_start:])
    if not isinstance(payload, dict):
        raise json.JSONDecodeError("response is not a JSON object", content, 0)
    return payload