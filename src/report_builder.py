"""Standalone HTML report builder.

Pulls together everything a user did in a session — profile, suggested charts,
every cached NLQ Q&A — into a single self-contained HTML page. Plotly is
loaded via CDN so the file opens without any local server.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from flask import render_template

from src import chart_suggester, profiler, storage


def build_report_context(session_id: str) -> dict[str, Any]:
    """Assemble the context dict the report template renders against."""
    session = storage.get_session(session_id)
    if session is None:
        raise ValueError(f"Unknown session: {session_id}")
    df = storage.load_dataframe(session_id)
    if df is None:
        raise ValueError(f"Dataframe missing for session: {session_id}")

    prof = profiler.profile(df)
    suggestions = chart_suggester.suggest_charts(prof)
    qa = storage.list_session_questions(session_id)

    return {
        "session": session.to_dict(),
        "profile": prof,
        "suggested_charts": suggestions,
        "qa": qa,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        # Pre-serialise for safe embedding in <script> blocks.
        "profile_json": json.dumps(prof, default=str),
        "qa_json": json.dumps(qa, default=str),
    }


def render_report_html(session_id: str) -> str:
    """Render the standalone report HTML for a session."""
    ctx = build_report_context(session_id)
    return render_template("report.html", **ctx)
