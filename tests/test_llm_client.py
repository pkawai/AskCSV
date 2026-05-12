"""Multi-provider LLM client tests — all calls mocked. No real API hits."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from openai import APIStatusError, BadRequestError

from src import llm_client as llm
from src.llm_client import (
    PROVIDERS,
    LLMClient,
    UsageStats,
    available_providers,
    switch_provider,
)


def _make_completion(input_tok: int = 100, output_tok: int = 20):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="hi", tool_calls=None), finish_reason="stop")],
        usage=SimpleNamespace(prompt_tokens=input_tok, completion_tokens=output_tok),
    )


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Test isolation — each test starts with no cached client."""
    llm.reset_client_for_tests()


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------


def test_init_defaults_to_gemini_when_provider_env_unset(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    c = LLMClient()
    assert c.provider == "gemini"


def test_init_respects_LLM_PROVIDER_env(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    c = LLMClient()
    assert c.provider == "groq"


def test_init_rejects_unknown_provider(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "made-up")
    with pytest.raises(RuntimeError, match="Unknown LLM provider"):
        LLMClient()


def test_init_requires_provider_specific_key(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GROQ_API_KEY"):
        LLMClient()


def test_explicit_provider_overrides_env(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    c = LLMClient(provider="groq")
    assert c.provider == "groq"


# ---------------------------------------------------------------------------
# chat()
# ---------------------------------------------------------------------------


@pytest.fixture()
def groq_client(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    return LLMClient(provider="groq")


@pytest.fixture()
def gemini_client(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    return LLMClient(provider="gemini")


def test_chat_records_usage_with_correct_model(groq_client):
    fake = _make_completion(input_tok=200, output_tok=50)
    with patch.object(groq_client._client.chat.completions, "create", return_value=fake):
        groq_client.chat(messages=[{"role": "user", "content": "hello"}])
    assert groq_client.usage.calls == 1
    assert groq_client.usage.total_input_tokens == 200
    assert groq_client.usage.per_model[PROVIDERS["groq"].primary] == 1


def test_chat_uses_gemini_model_when_provider_is_gemini(gemini_client):
    fake = _make_completion()
    with patch.object(gemini_client._client.chat.completions, "create", return_value=fake) as call:
        gemini_client.chat(messages=[{"role": "user", "content": "x"}])
    assert call.call_args.kwargs["model"] == PROVIDERS["gemini"].primary


def test_chat_falls_back_on_tool_use_failed(groq_client):
    fake_ok = _make_completion()
    err = BadRequestError(
        message="tool_use_failed: bad tool call",
        response=MagicMock(status_code=400),
        body=None,
    )
    with patch.object(
        groq_client._client.chat.completions, "create", side_effect=[err, fake_ok]
    ) as call:
        groq_client.chat(
            messages=[{"role": "user", "content": "x"}],
            tools=[{"type": "function", "function": {"name": "x", "parameters": {}}}],
        )
    assert call.call_count == 2
    assert call.call_args_list[0].kwargs["model"] == PROVIDERS["groq"].primary
    assert call.call_args_list[1].kwargs["model"] == PROVIDERS["groq"].fallback
    assert groq_client.usage.fallback_calls == 1


def test_chat_does_not_fall_back_on_other_400(groq_client):
    err = BadRequestError(
        message="invalid_request_error: something else",
        response=MagicMock(status_code=400),
        body=None,
    )
    with patch.object(groq_client._client.chat.completions, "create", side_effect=err):
        with pytest.raises(BadRequestError):
            groq_client.chat(messages=[{"role": "user", "content": "x"}])
    assert groq_client.usage.errors == 1


def test_chat_retries_on_5xx(groq_client):
    fake_ok = _make_completion()
    five_hundred = APIStatusError(
        message="server error",
        response=MagicMock(status_code=503),
        body=None,
    )
    with patch.object(
        groq_client._client.chat.completions,
        "create",
        side_effect=[five_hundred, five_hundred, fake_ok],
    ) as call:
        with patch("time.sleep"):
            groq_client.chat(messages=[{"role": "user", "content": "x"}], max_retries=3)
    assert call.call_count == 3
    assert groq_client.usage.calls == 1


# ---------------------------------------------------------------------------
# switch_provider + available_providers
# ---------------------------------------------------------------------------


def test_switch_provider_replaces_singleton(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gk")
    monkeypatch.setenv("GEMINI_API_KEY", "gemk")
    a = switch_provider("groq")
    assert a.provider == "groq"
    b = switch_provider("gemini")
    assert b.provider == "gemini"
    # Singleton actually swapped — get_client now returns the gemini one.
    assert llm.get_client() is b


def test_switch_provider_rejects_missing_key(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gk")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        switch_provider("gemini")


def test_available_providers_marks_configured(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gk")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    providers = {p["name"]: p for p in available_providers()}
    assert providers["groq"]["configured"] is True
    assert providers["gemini"]["configured"] is False


# ---------------------------------------------------------------------------
# UsageStats
# ---------------------------------------------------------------------------


def test_usage_stats_to_dict():
    u = UsageStats()
    u.record("model-a", 100, 20)
    u.record("model-a", 50, 10)
    u.fallback_calls = 1
    d = u.to_dict()
    assert d["calls"] == 2
    assert d["total_input_tokens"] == 150
    assert d["fallback_calls"] == 1
    assert d["per_model"]["model-a"] == 2
