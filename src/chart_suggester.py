"""Rule-based chart suggestions from a profile dict.

Pure heuristics — no LLM. We cap suggestions so the UI grid stays scannable.

Rules (priority order):
1. datetime + numeric -> line                 (time series wins)
2. categorical (<=12 unique) + numeric -> bar (grouped metric)
3. numeric + numeric                  -> scatter (correlation candidates)
4. single numeric                     -> hist  (distribution)
5. single categorical (<=8 unique)    -> pie/bar (share)
"""
from __future__ import annotations

from typing import Any

from src.cleaner import OUTLIER_SUFFIX

MAX_SUGGESTIONS = 6
LOW_CARD_BAR_LIMIT = 12
LOW_CARD_PIE_LIMIT = 8


def _is_real_column(col: dict[str, Any]) -> bool:
    """Skip outlier flag columns and other internals."""
    return not col["name"].endswith(OUTLIER_SUFFIX)


def _by_kind(profile: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    buckets: dict[str, list[dict[str, Any]]] = {
        "numeric": [],
        "datetime": [],
        "categorical": [],
        "boolean": [],
    }
    for col in profile["columns"]:
        if not _is_real_column(col):
            continue
        buckets.setdefault(col["kind"], []).append(col)
    return buckets


def suggest_charts(profile: dict[str, Any]) -> list[dict[str, Any]]:
    """Return up to MAX_SUGGESTIONS chart specs."""
    out: list[dict[str, Any]] = []
    buckets = _by_kind(profile)
    numeric = buckets["numeric"]
    datetime_cols = buckets["datetime"]
    categorical = buckets["categorical"]

    # Rule 1: datetime + numeric (line)
    for dt in datetime_cols:
        for num in numeric:
            out.append(
                {
                    "kind": "line",
                    "x": dt["name"],
                    "y": num["name"],
                    "title": f"{num['name']} over {dt['name']}",
                    "reason": "Time series of a numeric metric over a date column.",
                }
            )
            if len(out) >= MAX_SUGGESTIONS:
                return out

    # Rule 2: low-cardinality categorical + numeric (bar)
    for cat in categorical:
        if cat["unique_count"] > LOW_CARD_BAR_LIMIT:
            continue
        for num in numeric:
            out.append(
                {
                    "kind": "bar",
                    "x": cat["name"],
                    "y": num["name"],
                    "agg": "mean",
                    "title": f"Average {num['name']} by {cat['name']}",
                    "reason": f"Compare {num['name']} across {cat['unique_count']} categories.",
                }
            )
            if len(out) >= MAX_SUGGESTIONS:
                return out

    # Rule 3: numeric + numeric (scatter) — pick first 2 numerics if no correlation hint
    if len(numeric) >= 2:
        a, b = numeric[0], numeric[1]
        out.append(
            {
                "kind": "scatter",
                "x": a["name"],
                "y": b["name"],
                "title": f"{a['name']} vs {b['name']}",
                "reason": "Two numeric columns — check for relationship.",
            }
        )
        if len(out) >= MAX_SUGGESTIONS:
            return out

    # Rule 4: single numeric (hist) — pick the highest-variance one as most interesting
    if numeric:
        num = max(numeric, key=lambda c: c.get("std", 0) or 0)
        out.append(
            {
                "kind": "hist",
                "x": num["name"],
                "y": "count",
                "title": f"Distribution of {num['name']}",
                "reason": "Single-column distribution.",
            }
        )
        if len(out) >= MAX_SUGGESTIONS:
            return out

    # Rule 5: single low-card categorical (pie)
    for cat in categorical:
        if cat["unique_count"] <= LOW_CARD_PIE_LIMIT:
            out.append(
                {
                    "kind": "pie",
                    "x": cat["name"],
                    "y": "count",
                    "title": f"Share of {cat['name']}",
                    "reason": f"Low-cardinality category — show share of each of {cat['unique_count']} groups.",
                }
            )
            if len(out) >= MAX_SUGGESTIONS:
                return out

    return out
