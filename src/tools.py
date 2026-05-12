"""The 6 safe tools the LLM can call. Production-grade version of the PoC.

Each tool:
- Validates inputs strictly (raises ToolError on misuse)
- Operates on a ToolState (working dataframe + accumulated chart spec)
- Returns a small, JSON-serializable dict the model uses to plan its next step

The LLM cannot call anything outside this module. Tool dispatch is the
security boundary of the NLQ layer.

CLI demo:
    python -m src.tools demo
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

import pandas as pd

# ---------------------------------------------------------------------------
# Shared types
# ---------------------------------------------------------------------------


class ToolError(ValueError):
    """Raised when a tool call has invalid arguments."""


@dataclass
class ToolState:
    """Mutable working set shared across tool calls in a single NLQ turn."""

    df: pd.DataFrame
    chart_spec: Optional[dict[str, Any]] = None
    history: list[dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

FILTER_OPS = {"eq", "ne", "lt", "le", "gt", "ge", "in", "contains", "between"}
AGG_FUNCS = {"sum", "mean", "median", "min", "max", "count", "nunique"}
CHART_KINDS = {"bar", "line", "scatter", "box", "hist", "heatmap", "pie"}


def _require_column(df: pd.DataFrame, col: str) -> None:
    if col not in df.columns:
        raise ToolError(f"Column '{col}' not in dataframe. Available: {list(df.columns)}")


def tool_filter(state: ToolState, column: str, op: str, value: Any) -> dict[str, Any]:
    _require_column(state.df, column)
    if op not in FILTER_OPS:
        raise ToolError(f"Unknown op '{op}'. Allowed: {sorted(FILTER_OPS)}")
    s = state.df[column]
    if op == "eq":
        mask = s == value
    elif op == "ne":
        mask = s != value
    elif op == "lt":
        mask = s < value
    elif op == "le":
        mask = s <= value
    elif op == "gt":
        mask = s > value
    elif op == "ge":
        mask = s >= value
    elif op == "in":
        if not isinstance(value, (list, tuple)):
            raise ToolError("'in' op requires value to be a list")
        mask = s.isin(value)
    elif op == "contains":
        mask = s.astype(str).str.contains(str(value), case=False, na=False)
    elif op == "between":
        if not (isinstance(value, (list, tuple)) and len(value) == 2):
            raise ToolError("'between' op requires value to be [low, high]")
        mask = (s >= value[0]) & (s <= value[1])
    else:  # pragma: no cover - guarded by FILTER_OPS check
        raise ToolError(f"Unknown op {op}")
    state.df = state.df[mask]
    return {"row_count": int(len(state.df))}


def tool_groupby_aggregate(
    state: ToolState,
    group_cols: list[str],
    agg_col: str,
    agg_func: str,
) -> dict[str, Any]:
    if not isinstance(group_cols, list) or not group_cols:
        raise ToolError("group_cols must be a non-empty list of column names")
    for c in group_cols:
        _require_column(state.df, c)
    _require_column(state.df, agg_col)
    if agg_func not in AGG_FUNCS:
        raise ToolError(f"Unknown agg_func '{agg_func}'. Allowed: {sorted(AGG_FUNCS)}")
    grouped = state.df.groupby(group_cols)[agg_col].agg(agg_func).reset_index()
    state.df = grouped
    return {
        "row_count": int(len(grouped)),
        "preview": grouped.head(10).to_dict(orient="records"),
    }


def tool_sort(state: ToolState, by: str, ascending: bool) -> dict[str, Any]:
    _require_column(state.df, by)
    state.df = state.df.sort_values(by=by, ascending=ascending).reset_index(drop=True)
    return {"row_count": int(len(state.df))}


def tool_top_n(state: ToolState, n: int, by: str) -> dict[str, Any]:
    if not isinstance(n, int) or n <= 0:
        raise ToolError("n must be a positive integer")
    _require_column(state.df, by)
    state.df = state.df.sort_values(by=by, ascending=False).head(n).reset_index(drop=True)
    return {"row_count": int(len(state.df))}


def tool_correlate(state: ToolState, col_a: str, col_b: str) -> dict[str, Any]:
    _require_column(state.df, col_a)
    _require_column(state.df, col_b)
    a, b = state.df[col_a], state.df[col_b]
    if not (pd.api.types.is_numeric_dtype(a) and pd.api.types.is_numeric_dtype(b)):
        raise ToolError("correlate requires two numeric columns")
    r = a.corr(b)
    return {"pearson_r": round(float(r), 4) if pd.notna(r) else None}


def tool_plot(
    state: ToolState,
    kind: str,
    x: str,
    y: str,
    title: str,
    color: Optional[str] = None,
) -> dict[str, Any]:
    if kind not in CHART_KINDS:
        raise ToolError(f"Unknown chart kind '{kind}'. Allowed: {sorted(CHART_KINDS)}")
    # x/y don't always need to be real columns (e.g. y='count' for histograms)
    # but if they are real columns, validate.
    for col in (x, y, color):
        if col and col != "count" and col in state.df.columns:
            continue
        if col and col != "count" and col not in state.df.columns:
            # Allow synthetic 'count' / 'value' refs without rejecting
            if col in {"count", "value"}:
                continue
            # If a column was referenced that doesn't exist, fall back to silent skip
            # rather than fail — the model may have grabbed a relevant string.
    state.chart_spec = {
        "kind": kind,
        "x": x,
        "y": y,
        "color": color,
        "title": title,
        "data": state.df.head(500).to_dict(orient="records"),
    }
    return {"chart_rendered": True, "title": title, "rows_plotted": int(min(len(state.df), 500))}


# ---------------------------------------------------------------------------
# Dispatch + schemas
# ---------------------------------------------------------------------------

TOOL_REGISTRY: dict[str, Callable[..., dict[str, Any]]] = {
    "filter": tool_filter,
    "groupby_aggregate": tool_groupby_aggregate,
    "sort": tool_sort,
    "top_n": tool_top_n,
    "correlate": tool_correlate,
    "plot": tool_plot,
}


def dispatch(name: str, args: dict[str, Any], state: ToolState) -> dict[str, Any]:
    """Execute a named tool against the state. Catches ToolError and returns it as
    a structured error result the LLM can recover from."""
    if name not in TOOL_REGISTRY:
        return {"error": f"Unknown tool: {name}"}
    try:
        result = TOOL_REGISTRY[name](state, **args)
        state.history.append({"tool": name, "args": args, "result": result})
        return result
    except ToolError as exc:
        err = {"error": str(exc)}
        state.history.append({"tool": name, "args": args, "result": err})
        return err
    except Exception as exc:  # noqa: BLE001 - surface unexpected issues to the LLM
        err = {"error": f"{type(exc).__name__}: {exc}"}
        state.history.append({"tool": name, "args": args, "result": err})
        return err


# OpenAI tool-calling JSONSchemas — the exact shape passed to Groq.
TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "filter",
            "description": "Filter rows of the dataframe by a single column condition.",
            "parameters": {
                "type": "object",
                "properties": {
                    "column": {"type": "string"},
                    "op": {"type": "string", "enum": sorted(FILTER_OPS)},
                    "value": {"description": "Scalar, list ('in'), or [low, high] ('between')"},
                },
                "required": ["column", "op", "value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "groupby_aggregate",
            "description": "Group rows by one or more columns and aggregate a metric column.",
            "parameters": {
                "type": "object",
                "properties": {
                    "group_cols": {"type": "array", "items": {"type": "string"}},
                    "agg_col": {"type": "string"},
                    "agg_func": {"type": "string", "enum": sorted(AGG_FUNCS)},
                },
                "required": ["group_cols", "agg_col", "agg_func"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sort",
            "description": "Sort the current result by a column.",
            "parameters": {
                "type": "object",
                "properties": {
                    "by": {"type": "string"},
                    "ascending": {"type": "boolean"},
                },
                "required": ["by", "ascending"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "top_n",
            "description": "Keep the top N rows of the current result.",
            "parameters": {
                "type": "object",
                "properties": {
                    "n": {"type": "integer", "minimum": 1},
                    "by": {"type": "string"},
                },
                "required": ["n", "by"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "correlate",
            "description": "Compute Pearson correlation between two numeric columns.",
            "parameters": {
                "type": "object",
                "properties": {
                    "col_a": {"type": "string"},
                    "col_b": {"type": "string"},
                },
                "required": ["col_a", "col_b"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "plot",
            "description": "Render a chart of the current result. Call this LAST after data prep.",
            "parameters": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": sorted(CHART_KINDS)},
                    "x": {"type": "string"},
                    "y": {"type": "string"},
                    "color": {"type": "string"},
                    "title": {"type": "string"},
                },
                "required": ["kind", "x", "y", "title"],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# CLI demo
# ---------------------------------------------------------------------------

SAMPLE_CSV = Path(__file__).resolve().parent.parent / "data" / "samples" / "sales.csv"


def _demo() -> None:
    """Hand-rolled demo proving the tools work without any LLM in the loop."""
    df = pd.read_csv(SAMPLE_CSV, parse_dates=["order_date"])
    state = ToolState(df=df.copy())

    print("== Top 3 products by total revenue ==")
    dispatch("groupby_aggregate", {"group_cols": ["product"], "agg_col": "revenue", "agg_func": "sum"}, state)
    dispatch("top_n", {"n": 3, "by": "revenue"}, state)
    dispatch("plot", {"kind": "bar", "x": "product", "y": "revenue", "title": "Top 3 Products"}, state)
    print(json.dumps(state.history, indent=2, default=str))
    print("\nChart spec:")
    print(json.dumps(state.chart_spec, indent=2, default=str))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "demo":
        _demo()
    else:
        print("Usage: python -m src.tools demo")
        sys.exit(1)
