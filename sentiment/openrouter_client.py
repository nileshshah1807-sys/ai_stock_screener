"""Small resilient client for OpenRouter chat completions."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from typing import Any

import requests


logger = logging.getLogger(__name__)


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
        self.debug_response_content = os.getenv("OPENROUTER_DEBUG_RESPONSE_CONTENT", "false").lower() in {"1", "true", "yes"}
        self.debug_max_content_chars = _positive_int(os.getenv("OPENROUTER_DEBUG_MAX_CONTENT_CHARS"), 2000)
        self.max_output_tokens = _positive_int(os.getenv("OPENROUTER_MAX_OUTPUT_TOKENS"), 600)
        self.session = requests.Session()
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "X-Title": "AI Stock Screener",
        }

    def _request_payload(self, prompt: str) -> dict[str, Any]:
        return {
            "model": self.model_name,
            "temperature": 0,
            "max_tokens": self.max_output_tokens,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Return only a compact valid JSON object. Do not use Markdown, prose, or reasoning. "
                        "Keep each string under 160 characters and each array to at most three items."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        }

    def analyze_chunk(self, prompt: str) -> dict[str, Any]:
        payload = self._request_payload(prompt)
        logger.info(
            "OpenRouter settings: response_format=json_object max_output_tokens=%s debug_response_content=%s",
            self.max_output_tokens,
            self.debug_response_content,
        )
        for attempt in range(self.max_retries + 1):
            logger.info(
                "OpenRouter request: model=%s attempt=%s/%s prompt_chars=%s prompt_sha256=%s",
                self.model_name,
                attempt + 1,
                self.max_retries + 1,
                len(prompt),
                hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16],
            )
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
                body = response.json()
                choice = body["choices"][0]
                content = choice["message"]["content"]
                logger.info(
                    "OpenRouter response: model=%s status=%s finish_reason=%s content_chars=%s",
                    self.model_name,
                    response.status_code,
                    choice.get("finish_reason", "unknown"),
                    len(content) if isinstance(content, str) else "non-string",
                )
                if self.debug_response_content:
                    logger.info("OpenRouter response content: %s", _content_preview(content, self.debug_max_content_chars))
                return _parse_json_object(content)
            except (KeyError, IndexError, TypeError, AttributeError, json.JSONDecodeError) as exc:
                raise OpenRouterResponseError(f"OpenRouter returned invalid JSON content: {exc}") from exc
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


def _content_preview(content: Any, max_chars: int) -> str:
    text = content if isinstance(content, str) else repr(content)
    return text[:max_chars] + ("... [truncated]" if len(text) > max_chars else "")


def _positive_int(value: str | None, default: int) -> int:
    try:
        return max(1, int(value)) if value else default
    except ValueError:
        return default