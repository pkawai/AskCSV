"""Chart suggester tests: rule coverage."""
from __future__ import annotations

import pandas as pd

from src.chart_suggester import MAX_SUGGESTIONS, suggest_charts
from src.profiler import profile


def _suggest(df: pd.DataFrame) -> list[dict]:
    return suggest_charts(profile(df))


def test_datetime_plus_numeric_yields_line():
    df = pd.DataFrame(
        {"date": pd.to_datetime(["2025-01-01", "2025-01-02"]), "revenue": [100, 200]}
    )
    out = _suggest(df)
    assert any(s["kind"] == "line" and s["x"] == "date" and s["y"] == "revenue" for s in out)


def test_categorical_plus_numeric_yields_bar():
    df = pd.DataFrame(
        {"region": ["west", "east", "south", "north"], "revenue": [100, 200, 150, 250]}
    )
    out = _suggest(df)
    assert any(s["kind"] == "bar" and s["x"] == "region" and s["y"] == "revenue" for s in out)


def test_two_numerics_yield_scatter():
    df = pd.DataFrame({"x_val": [1, 2, 3, 4], "y_val": [2, 4, 6, 8]})
    out = _suggest(df)
    assert any(s["kind"] == "scatter" for s in out)


def test_single_numeric_yields_hist():
    df = pd.DataFrame({"score": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]})
    out = _suggest(df)
    assert any(s["kind"] == "hist" for s in out)


def test_single_low_card_categorical_yields_pie():
    df = pd.DataFrame({"status": ["a", "b", "c", "a", "b"]})
    out = _suggest(df)
    assert any(s["kind"] == "pie" for s in out)


def test_high_cardinality_categorical_skips_bar():
    # 50 unique categories should not be bar-charted against a numeric.
    df = pd.DataFrame(
        {"user_id": [f"u{i}" for i in range(50)], "score": list(range(50))}
    )
    out = _suggest(df)
    assert not any(s["kind"] == "bar" and s["x"] == "user_id" for s in out)


def test_cap_at_max_suggestions():
    # Build a wide df that would otherwise produce >MAX suggestions.
    cols = {f"num_{i}": list(range(10)) for i in range(6)}
    cols["region"] = ["a", "b", "c", "d", "e", "a", "b", "c", "d", "e"]
    cols["date"] = pd.to_datetime([f"2025-01-{i+1:02d}" for i in range(10)])
    df = pd.DataFrame(cols)
    out = _suggest(df)
    assert len(out) <= MAX_SUGGESTIONS


def test_outlier_flag_columns_excluded():
    df = pd.DataFrame({"x": list(range(10)), "x_is_outlier": [False] * 10})
    out = _suggest(df)
    # Should never suggest a chart referencing the outlier flag column.
    assert not any(s["x"] == "x_is_outlier" or s["y"] == "x_is_outlier" for s in out)
