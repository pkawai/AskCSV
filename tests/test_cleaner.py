"""Cleaner tests: dedup, null reporting, outlier flags."""
from __future__ import annotations

import pandas as pd
import pytest

from src.cleaner import OUTLIER_SUFFIX, clean


def test_removes_exact_duplicates():
    df = pd.DataFrame({"a": [1, 1, 2, 3], "b": ["x", "x", "y", "z"]})
    out, report = clean(df)
    assert report.duplicates_removed == 1
    assert report.original_rows == 4
    assert report.final_rows == 3


def test_null_counts_reported():
    df = pd.DataFrame({"a": [1, None, 3], "b": ["x", "y", None]})
    out, report = clean(df)
    assert report.null_counts["a"] == 1
    assert report.null_counts["b"] == 1
    # Cleaner does NOT impute.
    assert out["a"].isna().sum() == 1


def test_outlier_flag_added_for_numeric_with_variance():
    df = pd.DataFrame({"score": [10, 11, 12, 13, 14, 15, 16, 17, 18, 1000]})
    out, report = clean(df)
    flag_col = f"score{OUTLIER_SUFFIX}"
    assert flag_col in out.columns
    assert flag_col in report.outlier_columns
    # 1000 is clearly outside the IQR range.
    assert out.loc[out["score"] == 1000, flag_col].iloc[0] is True or out.loc[
        out["score"] == 1000, flag_col
    ].iloc[0] == True  # noqa: E712


def test_outlier_flag_skipped_for_low_unique():
    df = pd.DataFrame({"flag": [0, 1, 0, 1, 0, 1]})
    out, report = clean(df)
    assert f"flag{OUTLIER_SUFFIX}" not in out.columns


def test_outlier_flag_skipped_for_strings():
    df = pd.DataFrame({"name": ["alice", "bob", "carol", "dave", "eve"]})
    out, report = clean(df)
    assert f"name{OUTLIER_SUFFIX}" not in out.columns


def test_parsed_date_columns_reported():
    df = pd.DataFrame(
        {"d": pd.to_datetime(["2025-01-01", "2025-01-02", "2025-01-03"]), "x": [1, 2, 3]}
    )
    out, report = clean(df)
    assert "d" in report.parsed_date_columns


def test_empty_dataframe():
    df = pd.DataFrame()
    out, report = clean(df)
    assert report.original_rows == 0
    assert report.final_rows == 0
    assert report.duplicates_removed == 0
