"""AskCSV — Flask entry point.

Routes are added incrementally over PRs #2-#9. PR #1 ships only the
skeleton + a single index route so the smoke test passes.
"""
from __future__ import annotations

import io
import os
from pathlib import Path

from flask import Flask, jsonify, render_template, request

from src import (
    builder,
    chart_suggester,
    cleaner,
    groq_client,
    ingest,
    nlq_engine,
    profiler,
    report_builder,
    storage,
    suggester,
)

BASE_DIR = Path(__file__).resolve().parent


def create_app() -> Flask:
    """Application factory."""
    app = Flask(
        __name__,
        template_folder=str(BASE_DIR / "templates"),
        static_folder=str(BASE_DIR / "static"),
    )
    app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB upload cap

    @app.route("/")
    def index() -> str:
        return render_template("index.html")

    @app.route("/health")
    def health() -> dict:
        return {"status": "ok", "app": "AskCSV"}

    @app.route("/upload", methods=["POST"])
    def upload():
        """Accept a CSV upload, ingest + clean + persist. Return session metadata."""
        if "file" not in request.files:
            return jsonify({"error": "No file part in request"}), 400
        f = request.files["file"]
        if not f.filename:
            return jsonify({"error": "Empty filename"}), 400
        if not f.filename.lower().endswith(".csv"):
            return jsonify({"error": "Only .csv files are supported"}), 400

        try:
            raw = f.read()
            df, encoding = ingest.load_csv(raw)
            clean_df, report = cleaner.clean(df)
            session = storage.create_session_from_dataframe(
                clean_df, filename=f.filename, encoding=encoding
            )
        except Exception as exc:  # noqa: BLE001 - surface to client
            return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 400

        return jsonify(
            {
                "session": session.to_dict(),
                "cleaning_report": report.to_dict(),
            }
        )

    @app.route("/ask", methods=["POST"])
    def ask_route():
        """Run a single NLQ question against a session's dataframe.

        Optionally returns AI-generated follow-up questions when
        ``include_followups`` is true in the request body.
        """
        payload = request.get_json(silent=True) or {}
        session_id = payload.get("session_id")
        question = (payload.get("question") or "").strip()
        include_followups = bool(payload.get("include_followups", True))
        if not session_id or not question:
            return jsonify({"error": "session_id and question are required"}), 400
        try:
            result = nlq_engine.ask(session_id, question)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 404
        except Exception as exc:  # noqa: BLE001 - surface to client
            return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 500

        # Follow-ups are best-effort; failures shouldn't break the answer.
        if include_followups and result.get("chart_spec"):
            try:
                result["followups"] = suggester.suggest_followups(
                    question=question,
                    insight=result.get("insight", ""),
                    chart_kind=result["chart_spec"].get("kind", "bar"),
                )
            except Exception:  # noqa: BLE001
                result["followups"] = []
        else:
            result["followups"] = []
        return jsonify(result)

    @app.route("/suggest/<session_id>")
    def suggest_route(session_id: str):
        """AI-generated list of recommended analyses for this session."""
        try:
            suggestions = suggester.suggest_analyses(session_id)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 404
        except Exception as exc:  # noqa: BLE001
            return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 500
        return jsonify({"suggestions": suggestions})

    @app.route("/report/<session_id>")
    def report_route(session_id: str):
        """Standalone HTML report for a session — opens in a new tab."""
        try:
            return report_builder.render_report_html(session_id)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 404

    @app.route("/build_chart", methods=["POST"])
    def build_chart_route():
        """Manual chart builder — Tableau/Power-BI-style drop-zone path.

        Body: {session_id, kind, x, y?, color?, agg?, title?, save?}
        - save=true persists the chart into nlq_cache so it shows up in /report.
        """
        payload = request.get_json(silent=True) or {}
        try:
            result = builder.build(
                session_id=payload.get("session_id"),
                kind=payload.get("kind", ""),
                x=payload.get("x"),
                y=payload.get("y"),
                color=payload.get("color"),
                agg=payload.get("agg"),
                title=payload.get("title"),
            )
        except builder.BuilderError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:  # noqa: BLE001
            return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 500

        # Optional persistence so the export-report path picks it up.
        if payload.get("save"):
            session_id = payload.get("session_id")
            label = (
                payload.get("title")
                or f"Manual: {result['chart_spec'].get('kind')} of "
                f"{result['chart_spec'].get('y')} by {result['chart_spec'].get('x')}"
            )
            storage.save_cached_nlq(
                session_id,
                f"[builder] {label}",
                {
                    "chart_spec": result["chart_spec"],
                    "insight": "(built manually)",
                    "tool_trace": result["tool_trace"],
                    "from_cache": False,
                    "latency_s": 0.0,
                    "source": "manual",
                },
            )
            result["saved"] = True
        return jsonify(result)

    @app.route("/usage")
    def usage_route():
        """Process-lifetime LLM usage stats. Read by the UI's token chip."""
        try:
            client = groq_client.get_client()
            return jsonify(client.usage.to_dict())
        except RuntimeError:
            # GROQ_API_KEY not set — report zeros rather than 500.
            return jsonify({
                "total_input_tokens": 0,
                "total_output_tokens": 0,
                "calls": 0,
                "fallback_calls": 0,
                "errors": 0,
                "per_model": {},
                "configured": False,
            })

    @app.route("/profile/<session_id>")
    def profile_route(session_id: str):
        """Return per-column profile + suggested charts for an uploaded session."""
        session = storage.get_session(session_id)
        if session is None:
            return jsonify({"error": "Unknown session_id"}), 404
        df = storage.load_dataframe(session_id)
        if df is None:
            return jsonify({"error": "Dataframe missing for this session"}), 404
        prof = profiler.profile(df)
        suggestions = chart_suggester.suggest_charts(prof)
        return jsonify(
            {
                "session": session.to_dict(),
                "profile": prof,
                "suggested_charts": suggestions,
            }
        )

    return app


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=5000, debug=os.environ.get("FLASK_DEBUG") == "1")
