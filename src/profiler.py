"""Per-column profiling, correlation matrix, missing-value heatmap data.

Output is always JSON-friendly (lists/dicts of primitives) — meant to ship
straight to the frontend.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from src.cleaner import OUTLIER_SUFFIX

MAX_SAMPLE_VALUES = 3
TOP_CATEGORICAL_VALUES = 5


def _column_profile(s: pd.Series) -> dict[str, Any]:
    info: dict[str, Any] = {
        "name": s.name,
        "dtype": str(s.dtype),
        "null_count": int(s.isna().sum()),
        "unique_count": int(s.nunique(dropna=True)),
        "sample_values": [str(v) for v in s.dropna().head(MAX_SAMPLE_VALUES).tolist()],
    }
    if pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s):
        info["kind"] = "numeric"
        clean = s.dropna()
        if len(clean) > 0:
            info.update(
                {
                    "min": float(clean.min()),
                    "max": float(clean.max()),
                    "mean": round(float(clean.mean()), 4),
                    "median": round(float(clean.median()), 4),
                    "std": round(float(clean.std()), 4) if len(clean) > 1 else 0.0,
                }
            )
    elif pd.api.types.is_datetime64_any_dtype(s):
        info["kind"] = "datetime"
        clean = s.dropna()
        if len(clean) > 0:
            info["min"] = str(clean.min())
            info["max"] = str(clean.max())
    elif pd.api.types.is_bool_dtype(s):
        info["kind"] = "boolean"
        info["true_count"] = int(s.sum())
        info["false_count"] = int((~s.fillna(False)).sum())
    else:
        info["kind"] = "categorical"
        top = s.dropna().value_counts().head(TOP_CATEGORICAL_VALUES)
        info["top_values"] = [{"value": str(k), "count": int(v)} for k, v in top.items()]
    return info


def _correlation_matrix(df: pd.DataFrame) -> dict[str, Any]:
    """Pearson correlation among numeric columns (excluding outlier-flag bools)."""
    numeric = df.select_dtypes(include="number").copy()
    numeric = numeric.loc[:, ~numeric.columns.str.endswith(OUTLIER_SUFFIX)]
    if numeric.shape[1] < 2:
        return {"columns": list(numeric.columns), "values": []}
    corr = numeric.corr(numeric_only=True).round(4)
    return {
        "columns": list(corr.columns),
        "values": corr.values.tolist(),
    }


def _missing_value_matrix(df: pd.DataFrame) -> dict[str, Any]:
    """One bar per column with absolute null count + percent."""
    rows = int(len(df))
    return {
        "columns": list(df.columns),
        "null_counts": [int(df[c].isna().sum()) for c in df.columns],
        "null_pct": [
            round(float(df[c].isna().sum()) / rows * 100, 2) if rows else 0.0
            for c in df.columns
        ],
    }


def profile(df: pd.DataFrame) -> dict[str, Any]:
    """Build the full profile object the frontend renders."""
    return {
        "row_count": int(len(df)),
        "column_count": int(df.shape[1]),
        "columns": [_column_profile(df[c]) for c in df.columns],
        "correlation_matrix": _correlation_matrix(df),
        "missing_value_matrix": _missing_value_matrix(df),
    }
