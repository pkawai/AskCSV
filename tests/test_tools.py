"""Exhaustive tests for the 6 safe tools.

Covers each tool, each op/aggregate variant, error paths (bad columns,
wrong dtypes, malformed args), and the dispatcher.
"""
from __future__ import annotations

import pandas as pd
import pytest

from src.tools import (
    AGG_FUNCS,
    CHART_KINDS,
    FILTER_OPS,
    TOOL_REGISTRY,
    TOOL_SCHEMAS,
    ToolError,
    ToolState,
    dispatch,
    tool_correlate,
    tool_filter,
    tool_groupby_aggregate,
    tool_plot,
    tool_sort,
    tool_top_n,
)


@pytest.fixture()
def sample_df():
    return pd.DataFrame(
        {
            "region": ["west", "east", "west", "north", "south"],
            "product": ["a", "b", "a", "c", "b"],
            "quantity": [10, 5, 8, 12, 7],
            "price": [100.0, 200.0, 50.0, 300.0, 150.0],
            "date": pd.to_datetime(
                ["2025-01-01", "2025-01-02", "2025-01-03", "2025-01-04", "2025-01-05"]
            ),
        }
    )


# ---------------------------------------------------------------------------
# filter
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("op,value,expected_rows", [
    ("eq", "west", 2),
    ("ne", "west", 3),
    ("in", ["west", "east"], 3),
    ("contains", "ES", 2),  # case-insensitive: west/east
])
def test_filter_categorical_ops(sample_df, op, value, expected_rows):
    state = ToolState(df=sample_df.copy())
    res = tool_filter(state, "region", op, value)
    assert res["row_count"] == expected_rows


@pytest.mark.parametrize("op,value,expected_rows", [
    ("gt", 100, 3),
    ("ge", 100, 4),
    ("lt", 100, 1),
    ("le", 100, 2),
    ("between", [100, 200], 3),
])
def test_filter_numeric_ops(sample_df, op, value, expected_rows):
    state = ToolState(df=sample_df.copy())
    res = tool_filter(state, "price", op, value)
    assert res["row_count"] == expected_rows


def test_filter_rejects_unknown_column(sample_df):
    state = ToolState(df=sample_df.copy())
    with pytest.raises(ToolError, match="not in dataframe"):
        tool_filter(state, "nonexistent", "eq", 1)


def test_filter_rejects_unknown_op(sample_df):
    state = ToolState(df=sample_df.copy())
    with pytest.raises(ToolError, match="Unknown op"):
        tool_filter(state, "region", "noseq", "west")


def test_filter_in_requires_list(sample_df):
    state = ToolState(df=sample_df.copy())
    with pytest.raises(ToolError, match="list"):
        tool_filter(state, "region", "in", "west")


def test_filter_between_requires_pair(sample_df):
    state = ToolState(df=sample_df.copy())
    with pytest.raises(ToolError, match="\\[low, high\\]"):
        tool_filter(state, "price", "between", [100])


# ---------------------------------------------------------------------------
# groupby_aggregate
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("func", sorted(AGG_FUNCS))
def test_groupby_aggregate_every_func(sample_df, func):
    state = ToolState(df=sample_df.copy())
    res = tool_groupby_aggregate(state, ["region"], "price", func)
    assert res["row_count"] >= 1
    assert "preview" in res


def test_groupby_multi_column(sample_df):
    state = ToolState(df=sample_df.copy())
    res = tool_groupby_aggregate(state, ["region", "product"], "quantity", "sum")
    # 4 unique (region, product) pairs: (west,a) appears twice in the fixture.
    assert res["row_count"] == 4


def test_groupby_rejects_empty_group_cols(sample_df):
    state = ToolState(df=sample_df.copy())
    with pytest.raises(ToolError, match="non-empty"):
        tool_groupby_aggregate(state, [], "price", "sum")


def test_groupby_rejects_unknown_agg_col(sample_df):
    state = ToolState(df=sample_df.copy())
    with pytest.raises(ToolError, match="not in dataframe"):
        tool_groupby_aggregate(state, ["region"], "missing", "sum")


def test_groupby_rejects_unknown_agg_func(sample_df):
    state = ToolState(df=sample_df.copy())
    with pytest.raises(ToolError, match="Unknown agg_func"):
        tool_groupby_aggregate(state, ["region"], "price", "mode")


# ---------------------------------------------------------------------------
# sort / top_n
# ---------------------------------------------------------------------------


def test_sort_ascending(sample_df):
    state = ToolState(df=sample_df.copy())
    tool_sort(state, "price", True)
    assert state.df["price"].tolist() == sorted(sample_df["price"].tolist())


def test_sort_descending(sample_df):
    state = ToolState(df=sample_df.copy())
    tool_sort(state, "price", False)
    assert state.df["price"].tolist() == sorted(sample_df["price"].tolist(), reverse=True)


def test_top_n_keeps_n_rows(sample_df):
    state = ToolState(df=sample_df.copy())
    tool_top_n(state, 2, "price")
    assert len(state.df) == 2
    assert state.df["price"].tolist() == [300.0, 200.0]


def test_top_n_rejects_non_positive():
    df = pd.DataFrame({"x": [1, 2, 3]})
    state = ToolState(df=df.copy())
    with pytest.raises(ToolError, match="positive"):
        tool_top_n(state, 0, "x")


# ---------------------------------------------------------------------------
# correlate
# ---------------------------------------------------------------------------


def test_correlate_returns_pearson_r(sample_df):
    state = ToolState(df=sample_df.copy())
    res = tool_correlate(state, "quantity", "price")
    assert "pearson_r" in res
    assert -1 <= res["pearson_r"] <= 1


def test_correlate_rejects_non_numeric(sample_df):
    state = ToolState(df=sample_df.copy())
    with pytest.raises(ToolError, match="numeric"):
        tool_correlate(state, "region", "price")


# ---------------------------------------------------------------------------
# plot
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", sorted(CHART_KINDS))
def test_plot_accepts_every_kind(sample_df, kind):
    state = ToolState(df=sample_df.copy())
    res = tool_plot(state, kind, "region", "price", "title")
    assert res["chart_rendered"] is True
    assert state.chart_spec["kind"] == kind


def test_plot_rejects_unknown_kind(sample_df):
    state = ToolState(df=sample_df.copy())
    with pytest.raises(ToolError, match="Unknown chart kind"):
        tool_plot(state, "stacked_pancake", "region", "price", "title")


# ---------------------------------------------------------------------------
# dispatch + registry + schemas
# ---------------------------------------------------------------------------


def test_dispatch_unknown_tool_returns_error(sample_df):
    state = ToolState(df=sample_df.copy())
    res = dispatch("eval_arbitrary_code", {}, state)
    assert "error" in res


def test_dispatch_catches_tool_errors(sample_df):
    state = ToolState(df=sample_df.copy())
    res = dispatch("filter", {"column": "ghost", "op": "eq", "value": 1}, state)
    assert "error" in res
    # History records the failure too.
    assert state.history[-1]["result"] == res


def test_dispatch_records_history(sample_df):
    state = ToolState(df=sample_df.copy())
    dispatch("groupby_aggregate", {"group_cols": ["region"], "agg_col": "price", "agg_func": "sum"}, state)
    dispatch("plot", {"kind": "bar", "x": "region", "y": "price", "title": "T"}, state)
    assert len(state.history) == 2
    assert state.history[0]["tool"] == "groupby_aggregate"
    assert state.history[1]["tool"] == "plot"


def test_tool_registry_matches_filter_ops_set():
    """Every tool in the registry has a matching schema."""
    schema_names = {s["function"]["name"] for s in TOOL_SCHEMAS}
    assert set(TOOL_REGISTRY.keys()) == schema_names


def test_filter_op_enum_in_schema():
    filter_schema = next(s for s in TOOL_SCHEMAS if s["function"]["name"] == "filter")
    assert set(filter_schema["function"]["parameters"]["properties"]["op"]["enum"]) == FILTER_OPS
