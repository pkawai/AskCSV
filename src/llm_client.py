"""Multi-provider LLM wrapper.

Supports Groq and Google Gemini via their OpenAI-compatible endpoints so we
can keep using the `openai` Python SDK and one tool-calling format across
the whole app. The active provider is chosen by the LLM_PROVIDER env var
(default: gemini) and can be swapped at runtime via switch_provider().

Why two providers:
- Groq's Llama 3.3 70B is very fast but emits malformed tool calls ~10-15%
  of the time on multi-step chains. We handle that with a fallback model.
- Gemini 2.5 Flash has production-grade function calling and a more
  generous free tier (1,500 RPD vs Groq's 1,000) with much more predictable
  latency. It's the default for demo reliability.

Switching at runtime is useful for the Week 16 demo ("watch me hot-swap
LLM providers without restarting the server").
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from openai import APIStatusError, BadRequestError, OpenAI
from openai.types.chat import ChatCompletion

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    base_url: str
    env_key: str
    primary: str
    fallback: Optional[str]
    description: str


PROVIDERS: dict[str, ProviderConfig] = {
    "groq": ProviderConfig(
        name="groq",
        base_url="https://api.groq.com/openai/v1",
        env_key="GROQ_API_KEY",
        primary="llama-3.3-70b-versatile",
        fallback="openai/gpt-oss-120b",
        description="Groq — Llama 3.3 70B (fast, free, 1000 RPD)",
    ),
    "gemini": ProviderConfig(
        name="gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        env_key="GEMINI_API_KEY",
        primary="gemini-2.5-flash",
        fallback="gemini-2.0-flash",
        description="Google Gemini 2.5 Flash (free, 1500 RPD, reliable tools)",
    ),
}

DEFAULT_PROVIDER = "gemini"


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


class LLMClient:
    """Single wrapper over either Groq or Gemini. Provider chosen at construction."""

    def __init__(self, provider: Optional[str] = None) -> None:
        provider = provider or os.environ.get("LLM_PROVIDER") or DEFAULT_PROVIDER
        if provider not in PROVIDERS:
            raise RuntimeError(
                f"Unknown LLM provider '{provider}'. Allowed: {sorted(PROVIDERS)}"
            )
        cfg = PROVIDERS[provider]
        key = os.environ.get(cfg.env_key)
        if not key:
            raise RuntimeError(
                f"{cfg.env_key} is not set. Add it to .env or export it."
            )
        self.config = cfg
        self._client = OpenAI(api_key=key, base_url=cfg.base_url)
        self.usage = UsageStats()

    @property
    def provider(self) -> str:
        return self.config.name

    @property
    def primary_model(self) -> str:
        return self.config.primary

    @property
    def fallback_model(self) -> Optional[str]:
        return self.config.fallback

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
        model: Optional[str] = None,
        max_tokens: int = 1024,
        max_retries: int = 3,
        response_format: Optional[dict[str, Any]] = None,
    ) -> ChatCompletion:
        """Send a chat completion. Falls back on tool_use_failed, retries on 5xx."""
        target_model = model or self.primary_model
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
                # Groq's Llama can emit non-JSON tool calls. Fall back once.
                if (
                    "tool_use_failed" in str(exc)
                    and self.fallback_model
                    and target_model != self.fallback_model
                ):
                    logger.warning(
                        "tool_use_failed on %s, falling back to %s",
                        target_model,
                        self.fallback_model,
                    )
                    target_model = self.fallback_model
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
                if 500 <= exc.status_code < 600 and attempt < max_retries - 1:
                    sleep_s = min(2 ** attempt, 8)
                    logger.warning(
                        "%s on %s; retrying in %ss",
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

        self.usage.errors += 1
        raise last_err or RuntimeError("LLM chat failed without a specific error")

    def _record_usage(self, model: str, resp: ChatCompletion) -> None:
        usage = getattr(resp, "usage", None)
        if usage is None:
            return
        self.usage.record(model, usage.prompt_tokens, usage.completion_tokens)


# Module-level singleton — lazy so importing doesn't require an API key.
_singleton: Optional[LLMClient] = None


def get_client() -> LLMClient:
    global _singleton
    if _singleton is None:
        _singleton = LLMClient()
    return _singleton


def switch_provider(provider: str) -> LLMClient:
    """Hot-swap the active provider. Used by POST /llm to flip Groq <-> Gemini
    at runtime without restarting the server."""
    global _singleton
    new_client = LLMClient(provider=provider)
    _singleton = new_client
    return new_client


def available_providers() -> list[dict[str, Any]]:
    """List providers with whether their API key is configured."""
    return [
        {
            "name": cfg.name,
            "primary_model": cfg.primary,
            "fallback_model": cfg.fallback,
            "description": cfg.description,
            "configured": bool(os.environ.get(cfg.env_key)),
        }
        for cfg in PROVIDERS.values()
    ]


def reset_client_for_tests() -> None:
    """Test helper: nuke the singleton so tests can swap in mocks."""
    global _singleton
    _singleton = None
