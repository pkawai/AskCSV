"""Dataframe cleaning: dedup, null reporting, IQR outlier flags.

Philosophy: we do NOT silently impute or drop data. We report what we found.
Nulls stay as nulls. Outliers get a flag column the user can choose to act on.
"""
from __future__ import annotations

import pandas as pd

from src.models import CleaningReport

OUTLIER_IQR_MULTIPLIER = 1.5
OUTLIER_SUFFIX = "_is_outlier"


def _add_outlier_flags(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """For each numeric column with variance, add a boolean <col>_is_outlier column.

    Uses the classic IQR rule: outside [Q1 - 1.5*IQR, Q3 + 1.5*IQR].
    """
    added: list[str] = []
    for col in list(df.columns):
        if col.endswith(OUTLIER_SUFFIX):
            continue
        s = df[col]
        if not pd.api.types.is_numeric_dtype(s) or s.dropna().nunique() < 4:
            continue
        q1, q3 = s.quantile(0.25), s.quantile(0.75)
        iqr = q3 - q1
        if iqr == 0:
            continue
        low = q1 - OUTLIER_IQR_MULTIPLIER * iqr
        high = q3 + OUTLIER_IQR_MULTIPLIER * iqr
        flag_col = f"{col}{OUTLIER_SUFFIX}"
        df[flag_col] = (s < low) | (s > high)
        added.append(flag_col)
    return df, added


def clean(df: pd.DataFrame) -> tuple[pd.DataFrame, CleaningReport]:
    """Return a cleaned copy of df plus a CleaningReport describing what changed."""
    original_rows = len(df)

    # 1. Drop exact duplicate rows.
    df = df.drop_duplicates().reset_index(drop=True)
    deduped_rows = len(df)
    dupes_removed = original_rows - deduped_rows

    # 2. Record per-column null counts (no imputation).
    null_counts = {col: int(df[col].isna().sum()) for col in df.columns}

    # 3. Record date columns (ingest already converted them; we just report which).
    parsed_date_cols = [
        col for col in df.columns if pd.api.types.is_datetime64_any_dtype(df[col])
    ]

    # 4. Add outlier flag columns for numeric series.
    df, outlier_cols = _add_outlier_flags(df)

    return df, CleaningReport(
        original_rows=original_rows,
        final_rows=len(df),
        duplicates_removed=dupes_removed,
        parsed_date_columns=parsed_date_cols,
        outlier_columns=outlier_cols,
        null_counts=null_counts,
    )
