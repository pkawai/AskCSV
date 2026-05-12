"""CSV ingestion: encoding sniff, dtype coercion, datetime auto-detection.

Designed to handle the three common ugly cases:
- UTF-8 with BOM (Excel exports)
- Latin-1 / Windows-1252 (European CSVs)
- Semicolon delimiters (European Excel)
- Date columns in ISO, US, EU, or mixed formats
"""
from __future__ import annotations

import io
import warnings
from pathlib import Path
from typing import Union

import chardet
import pandas as pd

# Date formats to try, in priority order. First one to parse >= 90% of values wins.
DATE_FORMATS = [
    "%Y-%m-%d",        # ISO
    "%Y-%m-%d %H:%M:%S",
    "%Y/%m/%d",
    "%d/%m/%Y",        # EU
    "%m/%d/%Y",        # US
    "%d-%m-%Y",
    "%m-%d-%Y",
    "%Y%m%d",
]

# Delimiters tried in order. pandas auto-sniff is unreliable on semicolons.
DELIMITERS = [",", ";", "\t", "|"]


def _detect_encoding(raw: bytes) -> str:
    """Sniff encoding. Default to utf-8 on low confidence."""
    if not raw:
        return "utf-8"
    result = chardet.detect(raw[: 64 * 1024])  # sample is enough
    if result and result.get("confidence", 0) > 0.7:
        return (result.get("encoding") or "utf-8").lower()
    return "utf-8"


def _detect_delimiter(text_sample: str) -> str:
    """Pick the delimiter with the most consistent column count on the first 5 lines."""
    lines = [ln for ln in text_sample.splitlines()[:5] if ln.strip()]
    if not lines:
        return ","
    best_delim, best_score = ",", -1
    for delim in DELIMITERS:
        counts = [ln.count(delim) for ln in lines]
        if not any(counts):
            continue
        # Score: prefer high count, low variance.
        avg = sum(counts) / len(counts)
        var = sum((c - avg) ** 2 for c in counts) / len(counts)
        score = avg - var
        if score > best_score:
            best_score, best_delim = score, delim
    return best_delim


def _try_parse_dates(s: pd.Series) -> tuple[pd.Series, bool]:
    """Try to coerce an object/string Series to datetime. Returns (series, parsed?).

    pandas 3.0 introduced a native ``str`` dtype distinct from ``object``; we
    accept both so date detection works on CSVs loaded under either pandas major.
    """
    if not (pd.api.types.is_object_dtype(s) or pd.api.types.is_string_dtype(s)):
        return s, False
    non_null = s.dropna()
    if len(non_null) == 0:
        return s, False
    # First try pandas' native flexible parser on a sample.
    sample = non_null.sample(min(50, len(non_null)), random_state=0)
    for fmt in DATE_FORMATS:
        try:
            parsed_sample = pd.to_datetime(sample, format=fmt, errors="coerce")
            if parsed_sample.notna().mean() >= 0.9:
                return pd.to_datetime(s, format=fmt, errors="coerce"), True
        except (ValueError, TypeError):
            continue
    # Fallback: pandas flexible parser. Silence the "could not infer format"
    # UserWarning because that's exactly the case we're handling on purpose.
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=UserWarning)
            parsed_flex = pd.to_datetime(non_null, errors="coerce")
            if parsed_flex.notna().mean() >= 0.9:
                return pd.to_datetime(s, errors="coerce"), True
    except (ValueError, TypeError):
        pass
    return s, False


def load_csv(source: Union[str, Path, bytes, io.BytesIO]) -> tuple[pd.DataFrame, str]:
    """Load a CSV from a file path or raw bytes. Returns (dataframe, encoding_used).

    Auto-detects encoding and delimiter. Does NOT clean (that's cleaner.clean()).
    Does NOT detect dtypes beyond what pandas does natively, except for dates,
    which are detected here so downstream profiler sees them correctly.
    """
    if isinstance(source, (str, Path)):
        raw = Path(source).read_bytes()
    elif isinstance(source, io.BytesIO):
        raw = source.getvalue()
    else:
        raw = source

    encoding = _detect_encoding(raw)
    try:
        text_sample = raw[: 8 * 1024].decode(encoding, errors="replace")
    except LookupError:
        encoding = "utf-8"
        text_sample = raw[: 8 * 1024].decode("utf-8", errors="replace")

    delim = _detect_delimiter(text_sample)
    df = pd.read_csv(io.BytesIO(raw), encoding=encoding, sep=delim)

    # Detect date columns on object-typed series.
    for col in df.columns:
        new_series, parsed = _try_parse_dates(df[col])
        if parsed:
            df[col] = new_series

    return df, encoding
