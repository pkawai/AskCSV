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


def test_suggest_data_ideas_parses_json(session_id):
    payload = json.dumps(
        {
            "ideas": [
                {
                    "title": "Forecast monthly revenue",
                    "what": "Predict next quarter's revenue per region.",
                    "how": ["Aggregate by month + region", "Fit Prophet"],
                    "difficulty": "medium",
                    "category": "ml",
                },
                {
                    "title": "Segment customers",
                    "what": "Group buyers by purchase patterns.",
                    "how": ["K-means on quantity + revenue"],
                    "difficulty": "easy",
                    "category": "segmentation",
                },
            ]
        }
    )
    with patch.object(llm_client, "get_client", return_value=FakeClient(payload)):
        out = suggester.suggest_data_ideas(session_id)
    assert len(out) == 2
    assert out[0]["title"] == "Forecast monthly revenue"
    assert out[0]["category"] == "ml"
    assert out[0]["difficulty"] == "medium"


def test_suggest_data_ideas_caps_at_max(session_id):
    many = json.dumps(
        {"ideas": [{"title": f"i{i}", "what": "x", "how": ["a"]} for i in range(20)]}
    )
    with patch.object(llm_client, "get_client", return_value=FakeClient(many)):
        out = suggester.suggest_data_ideas(session_id)
    assert len(out) <= suggester.MAX_DATA_IDEAS


def test_suggest_data_ideas_normalizes_invalid_fields(session_id):
    payload = json.dumps(
        {
            "ideas": [
                {
                    "title": "x",
                    "what": "y",
                    "how": ["z"],
                    "difficulty": "extreme",
                    "category": "made-up",
                }
            ]
        }
    )
    with patch.object(llm_client, "get_client", return_value=FakeClient(payload)):
        out = suggester.suggest_data_ideas(session_id)
    assert out[0]["difficulty"] == "medium"
    assert out[0]["category"] == "analytics"


def test_suggest_data_ideas_handles_bad_json(session_id):
    with patch.object(llm_client, "get_client", return_value=FakeClient("nope")):
        assert suggester.suggest_data_ideas(session_id) == []


def test_suggest_data_ideas_accepts_projects_key(session_id):
    """Llama sometimes returns 'projects' instead of 'ideas'."""
    payload = json.dumps(
        {"projects": [{"title": "Forecast revenue", "what": "x", "how": ["a"]}]}
    )
    with patch.object(llm_client, "get_client", return_value=FakeClient(payload)):
        out = suggester.suggest_data_ideas(session_id)
    assert len(out) == 1
    assert out[0]["title"] == "Forecast revenue"


def test_suggest_data_ideas_accepts_name_synonym(session_id):
    """Some models use 'name' or 'description' instead of 'title' / 'what'."""
    payload = json.dumps(
        {
            "ideas": [
                {
                    "name": "CLV dashboard",
                    "description": "Lifetime value per customer.",
                    "steps": ["agg by customer_id", "show top 100"],
                    "level": "easy",
                    "type": "dashboard",
                }
            ]
        }
    )
    with patch.object(llm_client, "get_client", return_value=FakeClient(payload)):
        out = suggester.suggest_data_ideas(session_id)
    assert len(out) == 1
    assert out[0]["title"] == "CLV dashboard"
    assert out[0]["what"].startswith("Lifetime")
    assert out[0]["difficulty"] == "easy"
    assert out[0]["category"] == "dashboard"


def test_suggest_data_ideas_accepts_bare_list(session_id):
    """Some models drop the wrapper entirely and return a JSON array."""
    payload = json.dumps([{"title": "t1", "what": "w", "how": ["h"]}])
    with patch.object(llm_client, "get_client", return_value=FakeClient(payload)):
        out = suggester.suggest_data_ideas(session_id)
    assert len(out) == 1


def test_suggest_data_ideas_accepts_single_list_value(session_id):
    """If the LLM uses some random wrapper but there's only one list, take it."""
    payload = json.dumps(
        {"my_custom_wrapper": [{"title": "t1", "what": "w", "how": ["h"]}]}
    )
    with patch.object(llm_client, "get_client", return_value=FakeClient(payload)):
        out = suggester.suggest_data_ideas(session_id)
    assert len(out) == 1


def test_suggest_data_ideas_how_can_be_string(session_id):
    """Some models return 'how' as a single string instead of a list."""
    payload = json.dumps(
        {"ideas": [{"title": "t", "what": "w", "how": "one combined step"}]}
    )
    with patch.object(llm_client, "get_client", return_value=FakeClient(payload)):
        out = suggester.suggest_data_ideas(session_id)
    assert out[0]["how"] == ["one combined step"]
