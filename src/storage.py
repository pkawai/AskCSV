"""Storage: SQLite for session metadata, parquet for dataframes.

SQLite tables:
- sessions: one row per upload
- nlq_cache: (session_id, normalized_question) -> serialized response (PR #6)

Parquet files live in data/sessions/<session_id>.parquet (gitignored).
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from src.models import Session

BASE_DIR = Path(__file__).resolve().parent.parent
SESSIONS_DIR = BASE_DIR / "data" / "sessions"
DB_PATH = BASE_DIR / "data" / "askcsv.sqlite"


SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id   TEXT PRIMARY KEY,
    filename     TEXT NOT NULL,
    upload_ts    TEXT NOT NULL,
    row_count    INTEGER NOT NULL,
    column_count INTEGER NOT NULL,
    encoding     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS nlq_cache (
    session_id          TEXT NOT NULL,
    question_normalized TEXT NOT NULL,
    response_json       TEXT NOT NULL,
    created_ts          TEXT NOT NULL,
    PRIMARY KEY (session_id, question_normalized)
);
"""


def _connect() -> sqlite3.Connection:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    return conn


def new_session_id() -> str:
    """Short, URL-safe, no collisions for our scale."""
    return uuid.uuid4().hex[:12]


def save_session(session: Session, df: pd.DataFrame) -> None:
    """Persist session metadata to SQLite and the dataframe to parquet."""
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    parquet_path = SESSIONS_DIR / f"{session.session_id}.parquet"
    df.to_parquet(parquet_path, index=False)
    with _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO sessions VALUES (?, ?, ?, ?, ?, ?)",
            (
                session.session_id,
                session.filename,
                session.upload_ts.isoformat(),
                session.row_count,
                session.column_count,
                session.encoding,
            ),
        )


def get_session(session_id: str) -> Optional[Session]:
    with _connect() as conn:
        row = conn.execute(
            "SELECT session_id, filename, upload_ts, row_count, column_count, encoding "
            "FROM sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    if row is None:
        return None
    return Session(
        session_id=row[0],
        filename=row[1],
        upload_ts=datetime.fromisoformat(row[2]),
        row_count=row[3],
        column_count=row[4],
        encoding=row[5],
    )


def load_dataframe(session_id: str) -> Optional[pd.DataFrame]:
    path = SESSIONS_DIR / f"{session_id}.parquet"
    if not path.exists():
        return None
    return pd.read_parquet(path)


def create_session_from_dataframe(
    df: pd.DataFrame, filename: str, encoding: str
) -> Session:
    """Convenience: build a Session, persist, and return it."""
    session = Session(
        session_id=new_session_id(),
        filename=filename,
        upload_ts=datetime.now(timezone.utc),
        row_count=int(len(df)),
        column_count=int(df.shape[1]),
        encoding=encoding,
    )
    save_session(session, df)
    return session


# ---------------------------------------------------------------------------
# NLQ response cache
# ---------------------------------------------------------------------------


def _normalize_question(q: str) -> str:
    """Lowercase + collapse whitespace so 'X by Y' and 'x  by  y' share a cache row."""
    return " ".join(q.lower().split())


def get_cached_nlq(session_id: str, question: str) -> Optional[dict[str, Any]]:
    """Return the cached NLQ result dict, or None if no hit."""
    key = _normalize_question(question)
    with _connect() as conn:
        row = conn.execute(
            "SELECT response_json FROM nlq_cache "
            "WHERE session_id = ? AND question_normalized = ?",
            (session_id, key),
        ).fetchone()
    if row is None:
        return None
    return json.loads(row[0])


def save_cached_nlq(session_id: str, question: str, response: dict[str, Any]) -> None:
    """Persist an NLQ response for later cache hits."""
    key = _normalize_question(question)
    payload = json.dumps(response, default=str)
    with _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO nlq_cache VALUES (?, ?, ?, ?)",
            (
                session_id,
                key,
                payload,
                datetime.now(timezone.utc).isoformat(),
            ),
        )


def list_session_questions(session_id: str) -> list[dict[str, Any]]:
    """Return all cached questions for a session, oldest first.

    Used by the report builder to embed all Q&A pairs.
    """
    with _connect() as conn:
        rows = conn.execute(
            "SELECT question_normalized, response_json, created_ts "
            "FROM nlq_cache WHERE session_id = ? ORDER BY created_ts ASC",
            (session_id,),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for question, response_json, created_ts in rows:
        try:
            response = json.loads(response_json)
        except json.JSONDecodeError:
            continue
        out.append({"question": question, "response": response, "created_ts": created_ts})
    return out
