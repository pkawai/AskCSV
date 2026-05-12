"""Groq client tests — all calls mocked. No real API hits."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from openai import APIStatusError, BadRequestError

from src.groq_client import (
    FALLBACK_MODEL,
    PRIMARY_MODEL,
    GroqClient,
    UsageStats,
)


def _make_completion(input_tok: int = 100, output_tok: int = 20):
    """Minimal stand-in for an openai ChatCompletion."""
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="hi", tool_calls=None), finish_reason="stop")],
        usage=SimpleNamespace(prompt_tokens=input_tok, completion_tokens=output_tok),
    )


@pytest.fixture()
def client():
    return GroqClient(api_key="test-key")


def test_init_requires_api_key(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GROQ_API_KEY"):
        GroqClient()


def test_init_uses_env_var(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "from-env")
    c = GroqClient()
    assert c is not None


def test_chat_records_usage(client):
    fake = _make_completion(input_tok=200, output_tok=50)
    with patch.object(client._client.chat.completions, "create", return_value=fake) as call:
        client.chat(messages=[{"role": "user", "content": "hello"}])
        call.assert_called_once()
    assert client.usage.calls == 1
    assert client.usage.total_input_tokens == 200
    assert client.usage.total_output_tokens == 50
    assert client.usage.per_model[PRIMARY_MODEL] == 1


def test_chat_passes_tools_when_provided(client):
    fake = _make_completion()
    tools = [{"type": "function", "function": {"name": "x", "parameters": {}}}]
    with patch.object(client._client.chat.completions, "create", return_value=fake) as call:
        client.chat(messages=[{"role": "user", "content": "x"}], tools=tools)
    kwargs = call.call_args.kwargs
    assert kwargs["tools"] == tools
    assert kwargs["tool_choice"] == "auto"


def test_chat_falls_back_on_tool_use_failed(client):
    fake_ok = _make_completion()
    err = BadRequestError(
        message="tool_use_failed: bad tool call",
        response=MagicMock(status_code=400),
        body=None,
    )
    with patch.object(
        client._client.chat.completions,
        "create",
        side_effect=[err, fake_ok],
    ) as call:
        client.chat(messages=[{"role": "user", "content": "do thing"}], tools=[{"type": "function", "function": {"name": "x", "parameters": {}}}])
    # Two calls: first on primary, second on fallback.
    assert call.call_count == 2
    assert call.call_args_list[0].kwargs["model"] == PRIMARY_MODEL
    assert call.call_args_list[1].kwargs["model"] == FALLBACK_MODEL
    assert client.usage.fallback_calls == 1


def test_chat_does_not_fall_back_on_other_400(client):
    err = BadRequestError(
        message="invalid_request_error: something else",
        response=MagicMock(status_code=400),
        body=None,
    )
    with patch.object(client._client.chat.completions, "create", side_effect=err):
        with pytest.raises(BadRequestError):
            client.chat(messages=[{"role": "user", "content": "x"}])
    assert client.usage.errors == 1


def test_chat_retries_on_5xx(client):
    fake_ok = _make_completion()
    five_hundred = APIStatusError(
        message="server error",
        response=MagicMock(status_code=503),
        body=None,
    )
    with patch.object(
        client._client.chat.completions,
        "create",
        side_effect=[five_hundred, five_hundred, fake_ok],
    ) as call:
        with patch("time.sleep"):  # don't actually sleep in tests
            client.chat(messages=[{"role": "user", "content": "x"}], max_retries=3)
    assert call.call_count == 3
    assert client.usage.calls == 1  # only the successful one counts


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
