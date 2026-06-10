"""API smoke + behavior tests against the FastAPI serving layer.

Requires the serving bundle to exist (run `make serving-bundle` first).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.config import get_settings
from api.main import app


@pytest.fixture(scope="module")
def client():
    if not (get_settings().serving_dir / "tracts.json").exists():
        pytest.skip("serving bundle missing; run `make serving-bundle`")
    with TestClient(app) as c:  # triggers lifespan -> store.load()
        yield c


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["tracts"] > 2000
    assert body["model_loaded"] is True


def test_list_tracts(client):
    r = client.get("/api/tracts")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) > 2000
    assert {"geoid", "neighborhood", "borough", "risk_score"} <= rows[0].keys()


def test_tract_detail_and_comparison(client):
    geoid = client.get("/api/tracts").json()[0]["geoid"]
    r = client.get(f"/api/tract/{geoid}")
    assert r.status_code == 200
    body = r.json()
    assert body["geoid"] == geoid
    assert body["band"] in {"high", "elevated", "low"}
    assert len(body["metrics"]) == 5
    # Every comparison ratio is value / citywide_mean with a consistent direction.
    for m in body["metrics"]:
        if m["ratio"] is not None:
            assert (m["direction"] == "higher") == (m["ratio"] > 1)


def test_tract_404(client):
    r = client.get("/api/tract/00000000000")
    assert r.status_code == 404


def test_watchlist_directions(client):
    neglect = client.get("/api/watchlist", params={"direction": "neglect", "n": 10}).json()
    assert len(neglect) == 10
    residuals = [row["risk_residual"] for row in neglect]
    assert residuals == sorted(residuals, reverse=True)  # descending

    success = client.get("/api/watchlist", params={"direction": "success", "n": 10}).json()
    assert success[0]["risk_residual"] <= success[-1]["risk_residual"]

    surprise = client.get("/api/watchlist", params={"direction": "surprise", "n": 10}).json()
    abs_res = [abs(row["risk_residual"]) for row in surprise]
    assert abs_res == sorted(abs_res, reverse=True)


def test_watchlist_borough_filter(client):
    rows = client.get(
        "/api/watchlist", params={"borough": "Bronx", "n": 50}
    ).json()
    assert rows and all(row["borough"] == "Bronx" for row in rows)


def test_correlations(client):
    rows = client.get("/api/correlations").json()
    assert rows
    abs_r = [abs(row["r"]) for row in rows]
    assert abs_r == sorted(abs_r, reverse=True)
    assert all(-1.0 <= row["r"] <= 1.0 for row in rows)


def test_scatter(client):
    column = client.get("/api/correlations").json()[0]["column"]
    r = client.get(f"/api/scatter/{column}")
    assert r.status_code == 200
    body = r.json()
    assert body["column"] == column
    assert body["n"] == len(body["points"]) > 2000
    assert all(0 <= y <= 100 for _, y in body["points"])

    assert client.get("/api/scatter/not_a_column").status_code == 404


def test_model_info(client):
    body = client.get("/api/model").json()
    assert 0 <= body["r2"] <= 1
    assert body["rmse"] > 0
    assert set(body["labels"]) == set(body["features"])


def test_overlays(client):
    body = client.get("/api/overlays").json()
    labels = [o["label"] for o in body["overlays"]]
    assert "Risk Score" in labels
    assert body["residual_bins"][3] == 0.0  # symmetric, centered on zero


def test_predict_defaults_to_median(client):
    r = client.post("/api/predict", json={"inputs": {}})
    assert r.status_code == 200
    body = r.json()
    assert 0 <= body["predicted_risk"] <= 100
    assert body["band"] in {"high", "elevated", "low"}
    assert not body["clamped"]


def test_predict_clamps_out_of_range(client):
    r = client.post("/api/predict", json={"inputs": {"median_income": -999}})
    body = r.json()
    assert "median_income" in body["clamped"]
