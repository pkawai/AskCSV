"""Report builder + /report route tests."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from app import create_app
from src import report_builder, storage

SAMPLES = Path(__file__).resolve().parent.parent / "data" / "samples"


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "SESSIONS_DIR", tmp_path / "sessions")
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "askcsv.sqlite")
    (tmp_path / "sessions").mkdir(parents=True, exist_ok=True)


@pytest.fixture()
def client():
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


@pytest.fixture()
def session_id():
    df = pd.read_csv(SAMPLES / "sales.csv", parse_dates=["order_date"])
    return storage.create_session_from_dataframe(df, "sales.csv", "utf-8").session_id


def test_build_context_includes_profile_and_qa(session_id):
    storage.save_cached_nlq(
        session_id,
        "test question",
        {
            "insight": "test insight",
            "chart_spec": {"kind": "bar", "x": "region", "y": "revenue", "title": "T", "data": []},
            "tool_trace": [],
            "from_cache": False,
            "latency_s": 1.0,
        },
    )
    ctx = report_builder.build_report_context(session_id)
    assert ctx["session"]["row_count"] == 25
    assert ctx["profile"]["row_count"] == 25
    assert len(ctx["qa"]) == 1
    assert ctx["qa"][0]["question"] == "test question"


def test_build_context_unknown_session():
    with pytest.raises(ValueError, match="Unknown session"):
        report_builder.build_report_context("does-not-exist")


def test_report_route_returns_html(client, session_id):
    resp = client.get(f"/report/{session_id}")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "AskCSV report" in body
    assert "sales.csv" in body
    # Plotly script tag must be present so the standalone file works offline-after-load.
    assert "plotly" in body.lower()


def test_report_route_unknown_session(client):
    resp = client.get("/report/does-not-exist")
    assert resp.status_code == 404


def test_report_includes_qa_block(client, session_id):
    storage.save_cached_nlq(
        session_id,
        "revenue by region",
        {
            "insight": "West leads.",
            "chart_spec": {
                "kind": "bar",
                "x": "region",
                "y": "revenue",
                "title": "Revenue",
                "data": [{"region": "West", "revenue": 100}],
            },
            "tool_trace": [],
            "from_cache": False,
            "latency_s": 0.5,
        },
    )
    body = client.get(f"/report/{session_id}").get_data(as_text=True)
    assert "revenue by region" in body
    assert "West leads." in body


def test_list_session_questions_ordered(session_id):
    storage.save_cached_nlq(session_id, "q1", {"chart_spec": {"data": []}, "insight": "a"})
    storage.save_cached_nlq(session_id, "q2", {"chart_spec": {"data": []}, "insight": "b"})
    items = storage.list_session_questions(session_id)
    assert len(items) == 2
    # Insertion order preserved (ORDER BY created_ts ASC).
    assert items[0]["question"] == "q1"
    assert items[1]["question"] == "q2"
