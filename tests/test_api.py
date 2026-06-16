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


def test_tract_timeseries(client):
    """The endpoint mirrors timeseries.json (index-aligned, null-padded). Injected
    here so the test is independent of whether the real bundle ran the longitudinal
    loop (it requires a network fetch)."""
    from api.store import store

    geoid = client.get("/api/tracts").json()[0]["geoid"]
    sample = {
        "quarters": ["2024Q1", "2024Q2", "2024Q3"],
        "risk_score": [40.0, 55.0, None],          # null-padded where unscored
        "risk_residual": [-5.0, 3.0, None],
        "accountability_gap": [0.1, 0.2, None],
        "weighted_violation_rate": [0.3, 0.4, None],
        "avg_closure_time_adjusted": [12.0, 9.0, None],
        "vacate_rate": [0.0, 0.01, None],
    }
    store.timeseries[geoid] = sample
    try:
        r = client.get(f"/api/tract/{geoid}/timeseries")
        assert r.status_code == 200
        body = r.json()
        assert body["geoid"] == geoid
        assert body["quarters"] == sample["quarters"]
        assert body["risk_score"] == sample["risk_score"]
        assert body["risk_score"][2] is None       # alignment/null-padding preserved
        assert body["risk_residual"] == sample["risk_residual"]
    finally:
        store.timeseries.pop(geoid, None)


def test_tract_timeseries_404(client):
    # Unknown GEOID, and (when the bundle has no timeseries.json) any GEOID.
    assert client.get("/api/tract/00000000000/timeseries").status_code == 404


def test_timeseries_schema_rejects_misaligned_lists():
    """A per-quarter list whose length differs from quarters is a contract break
    (e.g. a truncated pipeline write) and must fail validation, not pass through."""
    from pydantic import ValidationError

    from api.schemas import TractTimeSeries

    aligned = dict(
        geoid="36005000100",
        quarters=["2024Q1", "2024Q2"],
        risk_score=[40.0, 55.0],
        accountability_gap=[0.1, 0.2],
        weighted_violation_rate=[0.3, 0.4],
        avg_closure_time_adjusted=[12.0, 9.0],
        vacate_rate=[0.0, 0.0],
    )
    TractTimeSeries(**aligned)  # well-formed: no error

    with pytest.raises(ValidationError):
        TractTimeSeries(**{**aligned, "risk_score": [40.0]})  # too short


def test_reload_without_timeseries_clears_stale_series(tmp_path):
    """Regression: a second load() from a bundle lacking timeseries.json must
    clear series carried over from a previous load (every other store field is
    reassigned unconditionally — timeseries must be too)."""
    import shutil

    from api.config import get_settings
    from api.store import DataStore

    real = get_settings().serving_dir
    if not (real / "tracts.json").exists():
        pytest.skip("serving bundle missing; run `make serving-bundle`")
    # Mirror the real bundle's required artifacts into a temp dir WITHOUT
    # timeseries.json, so the reload sees a bundle that has none.
    for name in ("tracts.json", "citywide_stats.json",
                 "demographic_model.json", "demographic_model.joblib"):
        shutil.copy2(real / name, tmp_path / name)

    s = DataStore()
    s.timeseries = {"STALE": {"quarters": ["2024Q1"], "risk_score": [1.0]}}
    s.load(tmp_path)
    assert s.timeseries == {}


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


def test_districts_endpoint(client):
    districts = client.get("/api/districts").json()
    if not districts:
        pytest.skip("bundle predates council districts; run `make patch-districts`")
    assert districts == sorted(districts)
    assert all(isinstance(d, int) for d in districts)
    assert len(districts) == 51


def test_council_district_in_rows(client):
    if not client.get("/api/districts").json():
        pytest.skip("bundle predates council districts; run `make patch-districts`")
    row = client.get("/api/watchlist", params={"n": 1}).json()[0]
    assert isinstance(row["council_district"], int)
    detail = client.get(f"/api/tract/{row['geoid']}").json()
    assert detail["council_district"] == row["council_district"]


def test_watchlist_district_filter(client):
    districts = client.get("/api/districts").json()
    if not districts:
        pytest.skip("bundle predates council districts; run `make patch-districts`")
    rows = client.get(
        "/api/watchlist", params={"district": districts[0], "n": 50}
    ).json()
    assert rows and all(r["council_district"] == districts[0] for r in rows)


def test_watchlist_richer_columns(client):
    row = client.get("/api/watchlist", params={"n": 1}).json()[0]
    assert "predicted_risk" in row and "median_income" in row


def test_watchlist_groups(client):
    for by in ("neighborhood", "council_district"):
        rows = client.get(
            "/api/watchlist/groups", params={"by": by, "n": 10, "min_tracts": 2}
        ).json()
        if by == "council_district" and not rows:
            pytest.skip("bundle predates council districts")
        assert rows
        means = [r["mean_residual"] for r in rows]
        assert means == sorted(means, reverse=True)  # neglect = descending
        assert all(r["tract_count"] >= 2 for r in rows)
        assert all(r["group_by"] == by for r in rows)


def test_tract_interpretation(client):
    # The top neglect tract is far outside the noise floor, so the
    # interpretation should name a driving component.
    top = client.get("/api/watchlist", params={"n": 1}).json()[0]
    detail = client.get(f"/api/tract/{top['geoid']}").json()
    assert detail["interpretation"]
    assert "vs. demographic prediction" in detail["interpretation"]
    if abs(detail["risk_residual"]) >= 10:
        assert "driver" in detail["interpretation"] or "metric" in detail["interpretation"]


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
