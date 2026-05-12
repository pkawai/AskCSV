"""Storage tests: SQLite + parquet round-trip."""
from __future__ import annotations

import pandas as pd
import pytest

from src import storage


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch):
    """Redirect storage paths into a tmp dir so tests don't pollute real data."""
    monkeypatch.setattr(storage, "SESSIONS_DIR", tmp_path / "sessions")
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "askcsv.sqlite")
    (tmp_path / "sessions").mkdir(parents=True, exist_ok=True)


def test_round_trip_dataframe():
    df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
    session = storage.create_session_from_dataframe(df, "test.csv", "utf-8")
    assert session.session_id
    assert session.row_count == 3
    assert session.column_count == 2

    loaded = storage.load_dataframe(session.session_id)
    pd.testing.assert_frame_equal(loaded, df)


def test_get_session_returns_metadata():
    df = pd.DataFrame({"x": [1]})
    session = storage.create_session_from_dataframe(df, "hello.csv", "utf-8")
    fetched = storage.get_session(session.session_id)
    assert fetched is not None
    assert fetched.filename == "hello.csv"
    assert fetched.row_count == 1


def test_get_session_returns_none_for_unknown_id():
    assert storage.get_session("does-not-exist") is None


def test_load_dataframe_returns_none_for_unknown_id():
    assert storage.load_dataframe("does-not-exist") is None


def test_session_id_is_unique():
    df = pd.DataFrame({"x": [1]})
    ids = {storage.create_session_from_dataframe(df, "a.csv", "utf-8").session_id for _ in range(5)}
    assert len(ids) == 5


# ---------- NLQ cache ----------


def test_nlq_cache_miss_then_hit():
    df = pd.DataFrame({"x": [1, 2, 3]})
    sid = storage.create_session_from_dataframe(df, "x.csv", "utf-8").session_id
    assert storage.get_cached_nlq(sid, "hello") is None
    storage.save_cached_nlq(sid, "hello", {"insight": "world", "latency_s": 0.1})
    cached = storage.get_cached_nlq(sid, "hello")
    assert cached["insight"] == "world"


def test_nlq_cache_normalizes_question():
    df = pd.DataFrame({"x": [1]})
    sid = storage.create_session_from_dataframe(df, "x.csv", "utf-8").session_id
    storage.save_cached_nlq(sid, "Show Revenue By Region", {"v": 1})
    # Case + whitespace variants should all hit the same row.
    assert storage.get_cached_nlq(sid, "show revenue by region")["v"] == 1
    assert storage.get_cached_nlq(sid, "  SHOW   revenue   BY region")["v"] == 1


def test_nlq_cache_scoped_per_session():
    df = pd.DataFrame({"x": [1]})
    a = storage.create_session_from_dataframe(df, "a.csv", "utf-8").session_id
    b = storage.create_session_from_dataframe(df, "b.csv", "utf-8").session_id
    storage.save_cached_nlq(a, "q", {"v": "a"})
    assert storage.get_cached_nlq(b, "q") is None
