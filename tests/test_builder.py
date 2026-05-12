"""Manual chart-builder tests + /build_chart route integration."""
from __future__ import annotations

import pandas as pd
import pytest

from app import create_app
from src import builder, storage


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "SESSIONS_DIR", tmp_path / "sessions")
    monkeypatch.setattr(storage, "DB_PATH", tmp_path / "askcsv.sqlite")
    (tmp_path / "sessions").mkdir(parents=True, exist_ok=True)


@pytest.fixture()
def sample_session():
    df = pd.DataFrame(
        {
            "region": ["west", "east", "west", "north", "south", "east"],
            "product": ["a", "b", "a", "c", "b", "a"],
            "quantity": [10, 5, 8, 12, 7, 6],
            "revenue": [100.0, 200.0, 150.0, 300.0, 175.0, 80.0],
            "date": pd.to_datetime(
                ["2025-01-01", "2025-01-02", "2025-01-03", "2025-01-04", "2025-01-05", "2025-01-06"]
            ),
        }
    )
    return storage.create_session_from_dataframe(df, "x.csv", "utf-8").session_id


@pytest.fixture()
def client():
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


# ---------- builder.build() ----------


def test_categorical_x_numeric_y_aggregates_sum(sample_session):
    out = builder.build(sample_session, "bar", x="region", y="revenue", agg="sum")
    spec = out["chart_spec"]
    assert spec["kind"] == "bar"
    # 4 unique regions
    assert len(spec["data"]) == 4
    # west sums to 100+150=250
    west = [r for r in spec["data"] if r["region"] == "west"][0]
    assert west["revenue"] == 250.0


def test_categorical_x_numeric_y_default_agg_is_sum(sample_session):
    out = builder.build(sample_session, "bar", x="region", y="revenue")  # no agg
    west = [r for r in out["chart_spec"]["data"] if r["region"] == "west"][0]
    assert west["revenue"] == 250.0


def test_categorical_x_numeric_y_mean(sample_session):
    out = builder.build(sample_session, "bar", x="region", y="revenue", agg="mean")
    west = [r for r in out["chart_spec"]["data"] if r["region"] == "west"][0]
    assert west["revenue"] == 125.0  # (100+150)/2


def test_numeric_x_numeric_y_scatter_no_aggregation(sample_session):
    out = builder.build(sample_session, "scatter", x="quantity", y="revenue")
    spec = out["chart_spec"]
    # No groupby — all 6 rows preserved.
    assert len(spec["data"]) == 6


def test_hist_requires_numeric_x(sample_session):
    out = builder.build(sample_session, "hist", x="revenue")
    assert out["chart_spec"]["kind"] == "hist"


def test_hist_rejects_categorical_x(sample_session):
    with pytest.raises(builder.BuilderError, match="numeric"):
        builder.build(sample_session, "hist", x="region")


def test_pie_groups_by_count(sample_session):
    out = builder.build(sample_session, "pie", x="region")
    spec = out["chart_spec"]
    assert spec["kind"] == "pie"
    # 4 unique regions → 4 slices.
    assert len(spec["data"]) == 4


def test_color_adds_grouping(sample_session):
    out = builder.build(sample_session, "bar", x="region", y="revenue", color="product", agg="sum")
    # Aggregating by (region, product) should produce more rows than by region alone.
    assert len(out["chart_spec"]["data"]) >= 4


def test_rejects_unknown_kind(sample_session):
    with pytest.raises(builder.BuilderError, match="Unknown chart kind"):
        builder.build(sample_session, "stacked_pancake", x="region", y="revenue")


def test_rejects_unknown_column(sample_session):
    with pytest.raises(builder.BuilderError, match="not in dataframe"):
        builder.build(sample_session, "bar", x="ghost", y="revenue")


def test_rejects_unknown_agg(sample_session):
    with pytest.raises(builder.BuilderError, match="Unknown aggregation"):
        builder.build(sample_session, "bar", x="region", y="revenue", agg="mode")


def test_two_column_kind_needs_both_axes(sample_session):
    with pytest.raises(builder.BuilderError, match="requires both"):
        builder.build(sample_session, "bar", x="region")


def test_unknown_session_raises():
    with pytest.raises(builder.BuilderError, match="Unknown session"):
        builder.build("does-not-exist", "bar", x="a", y="b")


# ---------- /build_chart route ----------


def test_build_chart_route_returns_spec(client, sample_session):
    resp = client.post(
        "/build_chart",
        json={"session_id": sample_session, "kind": "bar", "x": "region", "y": "revenue", "agg": "sum"},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["chart_spec"]["kind"] == "bar"
    assert body["source"] == "manual"


def test_build_chart_route_validation_error(client, sample_session):
    resp = client.post(
        "/build_chart",
        json={"session_id": sample_session, "kind": "nope", "x": "region", "y": "revenue"},
    )
    assert resp.status_code == 400


def test_build_chart_save_persists_to_cache(client, sample_session):
    resp = client.post(
        "/build_chart",
        json={
            "session_id": sample_session,
            "kind": "bar",
            "x": "region",
            "y": "revenue",
            "agg": "sum",
            "save": True,
        },
    )
    assert resp.status_code == 200
    assert resp.get_json().get("saved") is True
    # Stored in nlq_cache → list_session_questions picks it up for the report.
    items = storage.list_session_questions(sample_session)
    assert any("[builder]" in i["question"] for i in items)
