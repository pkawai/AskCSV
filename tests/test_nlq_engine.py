"""NLQ engine tests with a fully mocked Groq client.

We replace src.groq_client.get_client() with a fake whose .chat() returns
canned ChatCompletion-shaped objects, so the engine logic (tool dispatch,
loop termination, cache, error paths) is tested without any network.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import pytest

from src import groq_client, nlq_engine, storage


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "SESSIONS_DIR", tmp_path / "sessions")
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "askcsv.sqlite")
    (tmp_path / "sessions").mkdir(parents=True, exist_ok=True)


@pytest.fixture()
def session_id():
    """Persist a small sales dataframe and return its session id."""
    df = pd.DataFrame(
        {
            "region": ["west", "east", "west", "north", "south"],
            "revenue": [100, 200, 150, 250, 175],
        }
    )
    return storage.create_session_from_dataframe(df, "tiny.csv", "utf-8").session_id


def _tool_call(call_id: str, name: str, args: dict):
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=json.dumps(args)),
    )


def _completion(content: str = "", tool_calls=None):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content, tool_calls=tool_calls),
                finish_reason="stop" if tool_calls is None else "tool_calls",
            )
        ],
        usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20),
    )


class FakeClient:
    """Stand-in for GroqClient with a programmable .chat() queue."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses.pop(0)


def test_ask_runs_groupby_then_plot(session_id):
    """LLM chooses groupby_aggregate then plot. Engine returns chart + insight."""
    responses = [
        # Turn 1: tool_call -> groupby_aggregate
        _completion(
            tool_calls=[
                _tool_call(
                    "c1",
                    "groupby_aggregate",
                    {"group_cols": ["region"], "agg_col": "revenue", "agg_func": "sum"},
                )
            ]
        ),
        # Turn 2: tool_call -> plot
        _completion(
            tool_calls=[
                _tool_call(
                    "c2",
                    "plot",
                    {"kind": "bar", "x": "region", "y": "revenue", "title": "Revenue by region"},
                )
            ]
        ),
        # Turn 3: final text
        _completion(content="The West region leads with the highest revenue.", tool_calls=None),
    ]
    fake = FakeClient(responses)
    with patch.object(groq_client, "get_client", return_value=fake):
        result = nlq_engine.ask(session_id, "What is the total revenue by region?")
    assert result["chart_spec"] is not None
    assert result["chart_spec"]["kind"] == "bar"
    assert result["insight"].startswith("The West region")
    assert len(result["tool_trace"]) == 2
    assert result["from_cache"] is False


def test_ask_caches_results(session_id):
    """Identical question second time returns from cache without LLM calls."""
    responses = [
        _completion(
            tool_calls=[
                _tool_call(
                    "c1",
                    "plot",
                    {"kind": "bar", "x": "region", "y": "revenue", "title": "T"},
                )
            ]
        ),
        _completion(content="insight", tool_calls=None),
    ]
    fake = FakeClient(responses)
    with patch.object(groq_client, "get_client", return_value=fake):
        first = nlq_engine.ask(session_id, "show revenue by region")
        # Don't allow any more LLM calls — must hit cache.
        second = nlq_engine.ask(session_id, "Show  Revenue By  Region")  # case + whitespace differ
    assert first["from_cache"] is False
    assert second["from_cache"] is True
    assert second["chart_spec"] == first["chart_spec"]


def test_ask_does_not_cache_when_no_chart(session_id):
    """If the LLM gives up without plotting, we don't cache the empty result."""
    responses = [_completion(content="Can't answer with these columns.", tool_calls=None)]
    fake = FakeClient(responses)
    with patch.object(groq_client, "get_client", return_value=fake):
        result = nlq_engine.ask(session_id, "do something impossible")
    assert result["chart_spec"] is None
    # Second call would need another response — confirm cache miss by exhausted queue.
    responses2 = [_completion(content="Again, no.", tool_calls=None)]
    fake2 = FakeClient(responses2)
    with patch.object(groq_client, "get_client", return_value=fake2):
        result2 = nlq_engine.ask(session_id, "do something impossible")
    assert result2["from_cache"] is False


def test_ask_unknown_session():
    with pytest.raises(ValueError, match="Unknown session"):
        nlq_engine.ask("does-not-exist", "hello")


def test_ask_handles_tool_error_gracefully(session_id):
    """If the model picks a bad column, the tool dispatcher returns an error
    result; the LLM gets that feedback and can recover."""
    responses = [
        # Turn 1: bad column
        _completion(
            tool_calls=[
                _tool_call("c1", "filter", {"column": "nonexistent", "op": "eq", "value": 1})
            ]
        ),
        # Turn 2: recover -> plot
        _completion(
            tool_calls=[
                _tool_call(
                    "c2",
                    "plot",
                    {"kind": "bar", "x": "region", "y": "revenue", "title": "T"},
                )
            ]
        ),
        # Turn 3: final
        _completion(content="recovered", tool_calls=None),
    ]
    fake = FakeClient(responses)
    with patch.object(groq_client, "get_client", return_value=fake):
        result = nlq_engine.ask(session_id, "filter then plot")
    assert result["chart_spec"] is not None
    # First trace entry recorded the error.
    assert "error" in result["tool_trace"][0]["result"]


def test_build_schema_summary_omits_raw_rows():
    df = pd.DataFrame({"x": [1, 2, 3], "name": ["alice", "bob", "carol"]})
    summary = nlq_engine.build_schema_summary(df)
    assert summary["row_count"] == 3
    assert len(summary["columns"]) == 2
    # Only first 3 sample values per column, never the full data.
    for col in summary["columns"]:
        assert len(col["sample_values"]) <= 3
