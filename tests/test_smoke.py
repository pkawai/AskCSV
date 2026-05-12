"""Smoke tests for the Flask app shell. PR #1 baseline."""
from __future__ import annotations

import pytest

from app import create_app


@pytest.fixture()
def client():
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def test_index_renders(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"AskCSV" in resp.data


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload == {"status": "ok", "app": "AskCSV"}
