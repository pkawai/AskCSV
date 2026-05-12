"""Integration test for POST /upload — covers ingest + clean + storage end-to-end."""
from __future__ import annotations

import io
from pathlib import Path

import pytest

from app import create_app
from src import storage

SAMPLES = Path(__file__).resolve().parent.parent / "data" / "samples"


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "SESSIONS_DIR", tmp_path / "sessions")
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "askcsv.sqlite")
    (tmp_path / "sessions").mkdir(parents=True, exist_ok=True)


@pytest.fixture()
def client():
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def test_upload_sales_csv_returns_session(client):
    with open(SAMPLES / "sales.csv", "rb") as fh:
        resp = client.post(
            "/upload",
            data={"file": (fh, "sales.csv")},
            content_type="multipart/form-data",
        )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    payload = resp.get_json()
    assert "session" in payload
    assert payload["session"]["row_count"] == 25
    assert payload["session"]["column_count"] >= 8
    assert payload["cleaning_report"]["original_rows"] == 25


def test_upload_rejects_non_csv(client):
    resp = client.post(
        "/upload",
        data={"file": (io.BytesIO(b"hello"), "notes.txt")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400


def test_upload_rejects_missing_file(client):
    resp = client.post("/upload", data={}, content_type="multipart/form-data")
    assert resp.status_code == 400
