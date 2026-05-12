"""Suggester tests with mocked Groq client."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import pytest

from src import llm_client, storage, suggester


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "SESSIONS_DIR", tmp_path / "sessions")
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "askcsv.sqlite")
    (tmp_path / "sessions").mkdir(parents=True, exist_ok=True)


@pytest.fixture()
def session_id():
    df = pd.DataFrame(
        {"region": ["west", "east"], "revenue": [100, 200], "date": pd.to_datetime(["2025-01-01", "2025-02-01"])}
    )
    return storage.create_session_from_dataframe(df, "x.csv", "utf-8").session_id


def _completion(content: str):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=None))],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
    )


class FakeClient:
    def __init__(self, content: str):
        self._content = content
    def chat(self, **kwargs):
        return _completion(self._content)


def test_suggest_analyses_parses_json(session_id):
    payload = json.dumps(
        {
            "suggestions": [
                {"question": "Revenue by region?", "why": "comparison", "chart_kind": "bar"},
                {"question": "Trend over time?", "why": "time series", "chart_kind": "line"},
            ]
        }
    )
    with patch.object(llm_client, "get_client", return_value=FakeClient(payload)):
        out = suggester.suggest_analyses(session_id)
    assert len(out) == 2
    assert out[0]["question"] == "Revenue by region?"
    assert out[0]["chart_kind"] == "bar"


def test_suggest_analyses_caps_at_max(session_id):
    many = json.dumps(
        {"suggestions": [{"question": f"q{i}", "why": "x"} for i in range(20)]}
    )
    with patch.object(llm_client, "get_client", return_value=FakeClient(many)):
        out = suggester.suggest_analyses(session_id)
    assert len(out) <= suggester.MAX_SUGGESTIONS


def test_suggest_analyses_handles_bad_json(session_id):
    with patch.object(llm_client, "get_client", return_value=FakeClient("not json")):
        out = suggester.suggest_analyses(session_id)
    assert out == []


def test_suggest_analyses_skips_malformed_items(session_id):
    payload = json.dumps(
        {
            "suggestions": [
                {"question": "valid"},
                "string-not-dict",
                {"why": "missing question"},
                {"question": "also valid"},
            ]
        }
    )
    with patch.object(llm_client, "get_client", return_value=FakeClient(payload)):
        out = suggester.suggest_analyses(session_id)
    assert len(out) == 2


def test_suggest_analyses_unknown_session():
    with pytest.raises(ValueError, match="Unknown session"):
        suggester.suggest_analyses("does-not-exist")


def test_suggest_followups_parses_json():
    payload = json.dumps({"followups": ["q1", "q2", "q3"]})
    with patch.object(llm_client, "get_client", return_value=FakeClient(payload)):
        out = suggester.suggest_followups("orig", "an insight", "bar")
    assert out == ["q1", "q2", "q3"]


def test_suggest_followups_caps_at_max():
    payload = json.dumps({"followups": ["q1", "q2", "q3", "q4", "q5"]})
    with patch.object(llm_client, "get_client", return_value=FakeClient(payload)):
        out = suggester.suggest_followups("orig", "insight", "bar")
    assert len(out) <= suggester.MAX_FOLLOWUPS


def test_suggest_followups_handles_bad_json():
    with patch.object(llm_client, "get_client", return_value=FakeClient("nope")):
        out = suggester.suggest_followups("orig", "insight", "bar")
    assert out == []
