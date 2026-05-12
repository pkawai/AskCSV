"""AskCSV — Flask entry point.

Routes are added incrementally over PRs #2-#9. PR #1 ships only the
skeleton + a single index route so the smoke test passes.
"""
from __future__ import annotations

import os
from pathlib import Path

from flask import Flask, render_template

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

    return app


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=5000, debug=os.environ.get("FLASK_DEBUG") == "1")
