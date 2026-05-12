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


def test_profile_route_after_upload(client):
    with open(SAMPLES / "sales.csv", "rb") as fh:
        upload_resp = client.post(
            "/upload",
            data={"file": (fh, "sales.csv")},
            content_type="multipart/form-data",
        )
    session_id = upload_resp.get_json()["session"]["session_id"]
    prof_resp = client.get(f"/profile/{session_id}")
    assert prof_resp.status_code == 200
    data = prof_resp.get_json()
    assert "profile" in data
    assert "suggested_charts" in data
    assert data["profile"]["row_count"] == 25
    # sales.csv has datetime + numeric columns -> at least one suggestion.
    assert len(data["suggested_charts"]) > 0


def test_profile_route_unknown_session(client):
    resp = client.get("/profile/does-not-exist")
    assert resp.status_code == 404
