"""Thin wrapper around the OpenAI SDK pointed at Groq.

Responsibilities:
- Hold a single OpenAI client configured for https://api.groq.com/openai/v1.
- Provide a `chat()` method with model fallback on `tool_use_failed` (Llama 3.3
  occasionally emits malformed <function=...> tool calls; the larger
  gpt-oss-120b handles those cases reliably).
- Retry transient 5xx errors with exponential backoff.
- Track per-instance token usage for the UI's usage indicator.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from openai import APIStatusError, BadRequestError, OpenAI
from openai.types.chat import ChatCompletion

PRIMARY_MODEL = "llama-3.3-70b-versatile"
FALLBACK_MODEL = "openai/gpt-oss-120b"
GROQ_BASE_URL = "https://api.groq.com/openai/v1"

logger = logging.getLogger(__name__)


@dataclass
class UsageStats:
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    calls: int = 0
    fallback_calls: int = 0
    errors: int = 0
    per_model: dict[str, int] = field(default_factory=dict)

    def record(self, model: str, input_tokens: int, output_tokens: int) -> None:
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.calls += 1
        self.per_model[model] = self.per_model.get(model, 0) + 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "calls": self.calls,
            "fallback_calls": self.fallback_calls,
            "errors": self.errors,
            "per_model": dict(self.per_model),
        }


class GroqClient:
    """Single-purpose wrapper. One instance per Flask app."""

    def __init__(self, api_key: Optional[str] = None) -> None:
        key = api_key or os.environ.get("GROQ_API_KEY")
        if not key:
            raise RuntimeError(
                "GROQ_API_KEY is not set. Add it to .env or export it."
            )
        self._client = OpenAI(api_key=key, base_url=GROQ_BASE_URL)
        self.usage = UsageStats()

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
        model: Optional[str] = None,
        max_tokens: int = 1024,
        max_retries: int = 3,
        response_format: Optional[dict[str, Any]] = None,
    ) -> ChatCompletion:
        """Send a chat completion request with fallback + retry.

        - Tries `model` (default: PRIMARY_MODEL).
        - On `tool_use_failed` (Llama emits non-JSON tool calls), retries once
          on FALLBACK_MODEL with an extra reminder system message.
        - On 5xx, retries up to `max_retries` with exponential backoff.
        """
        target_model = model or PRIMARY_MODEL
        attempt = 0
        last_err: Optional[Exception] = None

        while attempt < max_retries:
            try:
                kwargs: dict[str, Any] = {
                    "model": target_model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                }
                if tools:
                    kwargs["tools"] = tools
                    kwargs["tool_choice"] = "auto"
                if response_format:
                    kwargs["response_format"] = response_format

                resp = self._client.chat.completions.create(**kwargs)
                self._record_usage(target_model, resp)
                return resp

            except BadRequestError as exc:
                # Llama 3.3 sometimes emits <function=...> syntax which Groq
                # validates and rejects. Fall back to gpt-oss-120b once.
                if "tool_use_failed" in str(exc) and target_model != FALLBACK_MODEL:
                    logger.warning(
                        "tool_use_failed on %s, falling back to %s",
                        target_model,
                        FALLBACK_MODEL,
                    )
                    target_model = FALLBACK_MODEL
                    messages = messages + [
                        {
                            "role": "system",
                            "content": (
                                "The previous response had a malformed tool call. "
                                "Use ONLY the OpenAI tool-calling JSON format. "
                                "Do NOT use <function=...></function> syntax."
                            ),
                        }
                    ]
                    self.usage.fallback_calls += 1
                    continue
                self.usage.errors += 1
                raise

            except APIStatusError as exc:
                # Retry transient 5xx with exponential backoff.
                if 500 <= exc.status_code < 600 and attempt < max_retries - 1:
                    sleep_s = min(2 ** attempt, 8)
                    logger.warning(
                        "Groq %s on %s; retrying in %ss",
                        exc.status_code,
                        target_model,
                        sleep_s,
                    )
                    time.sleep(sleep_s)
                    attempt += 1
                    last_err = exc
                    continue
                self.usage.errors += 1
                raise

        # Exhausted retries
        self.usage.errors += 1
        raise last_err or RuntimeError("Groq chat failed without a specific error")

    def _record_usage(self, model: str, resp: ChatCompletion) -> None:
        usage = getattr(resp, "usage", None)
        if usage is None:
            return
        self.usage.record(model, usage.prompt_tokens, usage.completion_tokens)


# Module-level singleton accessor — lazy so import doesn't require GROQ_API_KEY.
_singleton: Optional[GroqClient] = None


def get_client() -> GroqClient:
    global _singleton
    if _singleton is None:
        _singleton = GroqClient()
    return _singleton


def reset_client_for_tests() -> None:
    """Test helper: nuke the singleton so tests can swap in mocks."""
    global _singleton
    _singleton = None
