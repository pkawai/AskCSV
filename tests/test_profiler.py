"""Profiler tests: dtype detection, stats, correlation, missing values."""
from __future__ import annotations

import pandas as pd

from src.profiler import profile


def test_basic_shape():
    df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
    out = profile(df)
    assert out["row_count"] == 3
    assert out["column_count"] == 2
    assert len(out["columns"]) == 2


def test_numeric_column_has_stats():
    df = pd.DataFrame({"price": [10, 20, 30, 40, 50]})
    out = profile(df)
    col = out["columns"][0]
    assert col["kind"] == "numeric"
    assert col["min"] == 10.0
    assert col["max"] == 50.0
    assert col["mean"] == 30.0
    assert col["median"] == 30.0


def test_datetime_column_detected():
    df = pd.DataFrame({"d": pd.to_datetime(["2025-01-01", "2025-06-15", "2025-12-31"])})
    out = profile(df)
    col = out["columns"][0]
    assert col["kind"] == "datetime"
    assert "2025-01-01" in col["min"]
    assert "2025-12-31" in col["max"]


def test_categorical_top_values():
    df = pd.DataFrame({"region": ["west", "east", "west", "north", "west", "east"]})
    out = profile(df)
    col = out["columns"][0]
    assert col["kind"] == "categorical"
    assert col["top_values"][0]["value"] == "west"
    assert col["top_values"][0]["count"] == 3


def test_correlation_matrix_for_numerics():
    df = pd.DataFrame({"a": [1, 2, 3, 4, 5], "b": [2, 4, 6, 8, 10], "c": ["x", "y", "z", "x", "y"]})
    out = profile(df)
    corr = out["correlation_matrix"]
    assert set(corr["columns"]) == {"a", "b"}
    # Perfect linear -> r=1
    idx_a = corr["columns"].index("a")
    idx_b = corr["columns"].index("b")
    assert corr["values"][idx_a][idx_b] == 1.0


def test_correlation_matrix_skipped_for_single_numeric():
    df = pd.DataFrame({"a": [1, 2, 3], "name": ["x", "y", "z"]})
    out = profile(df)
    assert out["correlation_matrix"]["values"] == []


def test_missing_value_matrix():
    df = pd.DataFrame({"a": [1, None, 3], "b": [None, None, "z"]})
    out = profile(df)
    mvm = out["missing_value_matrix"]
    assert mvm["columns"] == ["a", "b"]
    assert mvm["null_counts"] == [1, 2]
    assert mvm["null_pct"] == [pytest_approx(33.33), pytest_approx(66.67)]


def pytest_approx(v):
    """Tiny helper for tolerant float comparison."""
    import pytest
    return pytest.approx(v, rel=0.01)
