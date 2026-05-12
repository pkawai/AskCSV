"""Manual chart builder — the Tableau/Power BI-style drop-zone path.

The frontend lets the user drag column chips onto X, Y, and Color shelves
plus pick a chart kind and (optionally) an aggregation function. This
module turns that spec into a chart spec by reusing the same safe tools
the NLQ engine uses, so the security boundary stays the same.

Inputs are validated strictly:
- columns must exist in the session's dataframe
- chart kind must be one of the allowed set
- aggregation only makes sense for numeric Y over categorical/datetime X
"""
from __future__ import annotations

from typing import Any, Optional

import pandas as pd

from src import storage, tools

# Mirror tools.AGG_FUNCS and tools.CHART_KINDS so the route can validate
# before touching the dataframe.
ALLOWED_AGG: set[str] = set(tools.AGG_FUNCS)
ALLOWED_KINDS: set[str] = set(tools.CHART_KINDS)


class BuilderError(ValueError):
    """Raised when the chart-builder spec is invalid."""


def _is_categorical_like(s: pd.Series) -> bool:
    """For builder purposes: anything not numeric and not datetime is categorical."""
    if pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s):
        return False
    if pd.api.types.is_datetime64_any_dtype(s):
        return False
    return True


def _is_numeric(s: pd.Series) -> bool:
    return pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s)


def build(
    session_id: str,
    kind: str,
    x: Optional[str],
    y: Optional[str] = None,
    color: Optional[str] = None,
    agg: Optional[str] = None,
    title: Optional[str] = None,
) -> dict[str, Any]:
    """Build a chart spec from a manual drop-zone configuration.

    Returns a chart_spec compatible with the frontend's renderPlotlySpec()
    (same shape produced by the LLM's `plot` tool).
    """
    if kind not in ALLOWED_KINDS:
        raise BuilderError(f"Unknown chart kind '{kind}'. Allowed: {sorted(ALLOWED_KINDS)}")

    df = storage.load_dataframe(session_id)
    if df is None:
        raise BuilderError(f"Unknown session: {session_id}")

    if x and x not in df.columns:
        raise BuilderError(f"Column '{x}' not in dataframe")
    if y and y not in df.columns:
        raise BuilderError(f"Column '{y}' not in dataframe")
    if color and color not in df.columns:
        raise BuilderError(f"Column '{color}' not in dataframe")
    if agg and agg not in ALLOWED_AGG:
        raise BuilderError(f"Unknown aggregation '{agg}'. Allowed: {sorted(ALLOWED_AGG)}")

    state = tools.ToolState(df=df.copy())

    # Single-column charts: hist for numeric x, pie/bar of counts for categorical.
    if kind == "hist":
        if not x or not _is_numeric(df[x]):
            raise BuilderError("hist requires a numeric column on X")
        return _wrap(state, kind, x=x, y="count", color=color, title=title or f"Distribution of {x}")

    if kind == "pie":
        if not x:
            raise BuilderError("pie requires a categorical column on X")
        # Counts share-of-X. pandas can't cleanly group by a column and count
        # itself, so pick any other column as the count target (count is
        # column-agnostic for non-null values).
        other_cols = [c for c in df.columns if c != x]
        if other_cols:
            agg_target = other_cols[0]
        else:
            state.df = state.df.assign(_n=1)
            agg_target = "_n"
        tools.dispatch(
            "groupby_aggregate",
            {"group_cols": [x], "agg_col": agg_target, "agg_func": "count"},
            state,
        )
        return _wrap(
            state,
            kind,
            x=x,
            y=agg_target,
            color=color,
            title=title or f"Share of {x}",
        )

    # Two-column charts. Decide whether to aggregate based on X's kind.
    if not x or not y:
        raise BuilderError(f"{kind} requires both X and Y columns")

    x_series, y_series = df[x], df[y]

    # When X is categorical or datetime AND Y is numeric, aggregate.
    # That mirrors Tableau's default behavior of auto-summing measures.
    if _is_numeric(y_series) and not _is_numeric(x_series):
        chosen_agg = agg or "sum"
        group_cols = [x] if not color else [x, color]
        tools.dispatch(
            "groupby_aggregate",
            {"group_cols": group_cols, "agg_col": y, "agg_func": chosen_agg},
            state,
        )

    return _wrap(state, kind, x=x, y=y, color=color, title=title or f"{y} by {x}")


def _wrap(
    state: tools.ToolState,
    kind: str,
    *,
    x: str,
    y: str,
    color: Optional[str],
    title: str,
) -> dict[str, Any]:
    """Final step: call the plot tool so the result shape matches NLQ output exactly."""
    args: dict[str, Any] = {"kind": kind, "x": x, "y": y, "title": title}
    if color:
        args["color"] = color
    tools.dispatch("plot", args, state)
    return {
        "chart_spec": state.chart_spec,
        "tool_trace": state.history,
        "source": "manual",
    }
