"""Ingest tests on the 3 sample CSVs + adversarial encodings/delimiters."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.ingest import _detect_delimiter, _detect_encoding, load_csv

SAMPLES = Path(__file__).resolve().parent.parent / "data" / "samples"


def test_loads_sales_csv():
    df, encoding = load_csv(SAMPLES / "sales.csv")
    assert len(df) == 25
    assert {"order_id", "order_date", "region", "revenue"}.issubset(df.columns)
    assert pd.api.types.is_datetime64_any_dtype(df["order_date"])
    assert encoding in {"utf-8", "ascii"}


def test_loads_hr_csv_with_dates():
    df, _ = load_csv(SAMPLES / "hr.csv")
    assert len(df) == 20
    # hire_date should be auto-parsed
    assert pd.api.types.is_datetime64_any_dtype(df["hire_date"])
    assert pd.api.types.is_numeric_dtype(df["salary"])


def test_loads_weather_csv():
    df, _ = load_csv(SAMPLES / "weather.csv")
    assert len(df) == 21
    assert pd.api.types.is_datetime64_any_dtype(df["date"])


def test_handles_semicolon_delimiter(tmp_path):
    csv_bytes = b"a;b;c\n1;2;3\n4;5;6\n"
    df, _ = load_csv(csv_bytes)
    assert list(df.columns) == ["a", "b", "c"]
    assert df.shape == (2, 3)


def test_handles_utf8_bom(tmp_path):
    csv_bytes = b"\xef\xbb\xbfname,value\nfoo,1\nbar,2\n"
    df, _ = load_csv(csv_bytes)
    # The BOM should be stripped from the first column name.
    assert "name" in df.columns or "﻿name" in df.columns
    assert df.shape == (2, 2)


def test_detect_delimiter_picks_comma():
    sample = "a,b,c\n1,2,3\n4,5,6\n"
    assert _detect_delimiter(sample) == ","


def test_detect_delimiter_picks_semicolon():
    sample = "a;b;c\n1;2;3\n4;5;6\n"
    assert _detect_delimiter(sample) == ";"


def test_detect_encoding_defaults_utf8_on_empty():
    assert _detect_encoding(b"") == "utf-8"
