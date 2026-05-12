"""Dataclasses shared across modules."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Session:
    """Metadata about an uploaded CSV. Raw rows live in parquet, keyed by session_id."""

    session_id: str
    filename: str
    upload_ts: datetime
    row_count: int
    column_count: int
    encoding: str

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "filename": self.filename,
            "upload_ts": self.upload_ts.isoformat(),
            "row_count": self.row_count,
            "column_count": self.column_count,
            "encoding": self.encoding,
        }


@dataclass
class CleaningReport:
    """Summary of what cleaner.clean() did to a dataframe. Shown to the user."""

    original_rows: int
    final_rows: int
    duplicates_removed: int
    parsed_date_columns: list[str] = field(default_factory=list)
    outlier_columns: list[str] = field(default_factory=list)
    null_counts: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "original_rows": self.original_rows,
            "final_rows": self.final_rows,
            "duplicates_removed": self.duplicates_removed,
            "parsed_date_columns": self.parsed_date_columns,
            "outlier_columns": self.outlier_columns,
            "null_counts": self.null_counts,
        }
