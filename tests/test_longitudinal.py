"""Unit tests for the longitudinal quarterly scoring loop.

The quarter math is tested directly; the loop is tested by stubbing the scoring
step (so no Socrata / geopandas work runs) and asserting the assembled
time-series schema. All offline."""
from __future__ import annotations

import pandas as pd
import pytest

from pipeline import longitudinal as lg


# ── Quarter math ─────────────────────────────────────────────────────────────

def test_quarter_bounds_all_quarters():
    assert lg.quarter_bounds("2024Q1") == ("2024-01-01", "2024-04-01")
    assert lg.quarter_bounds("2024Q2") == ("2024-04-01", "2024-07-01")
    assert lg.quarter_bounds("2024Q3") == ("2024-07-01", "2024-10-01")
    # Q4 must roll the year on the (exclusive) end.
    assert lg.quarter_bounds("2024Q4") == ("2024-10-01", "2025-01-01")


def test_rolling_bounds_spans_trailing_quarters():
    # A trailing 4Q window ending in 2024Q4 is exactly the calendar year.
    assert lg.rolling_bounds("2024Q4", 4) == ("2024-01-01", "2025-01-01")
    # Window of 1 collapses to the single quarter.
    assert lg.rolling_bounds("2024Q4", 1) == lg.quarter_bounds("2024Q4")
    # Crosses a year boundary backwards.
    assert lg.rolling_bounds("2025Q1", 2) == ("2024-10-01", "2025-04-01")


def test_quarters_between_inclusive_and_crosses_years():
    assert lg.quarters_between("2024Q1", "2024Q4") == [
        "2024Q1", "2024Q2", "2024Q3", "2024Q4"]
    assert lg.quarters_between("2024Q3", "2025Q1") == [
        "2024Q3", "2024Q4", "2025Q1"]
    assert lg.quarters_between("2024Q2", "2024Q2") == ["2024Q2"]


def test_quarter_label_validation():
    with pytest.raises(ValueError):
        lg.parse_quarter("2024-Q1")
    with pytest.raises(ValueError):
        lg.parse_quarter("2024Q5")
    with pytest.raises(ValueError):
        lg.quarters_between("2025Q1", "2024Q1")  # end precedes start


# ── Assembly schema ──────────────────────────────────────────────────────────

def _scored(geoid_to_score: dict[str, float]) -> pd.DataFrame:
    """A minimal scored frame like score_period returns."""
    return pd.DataFrame([
        {"GEOID": g, "risk_score": s, "accountability_gap": s / 10,
         "weighted_violation_rate": s / 100, "avg_closure_time_adjusted": 1.0,
         "vacate_rate": 0.0}
        for g, s in geoid_to_score.items()
    ])


def test_assemble_aligns_and_null_pads():
    quarters = ["2024Q1", "2024Q2"]
    scored = {
        "2024Q1": _scored({"A": 80.0, "B": 50.0}),
        "2024Q2": _scored({"A": 90.0}),  # B missing this quarter
    }
    series = lg._assemble(quarters, scored, predicted={"A": 70.0, "B": 40.0},
                          with_residual=True)

    assert series["A"]["quarters"] == quarters
    assert series["A"]["risk_score"] == [80.0, 90.0]
    # residual = score - fixed prediction
    assert series["A"]["risk_residual"] == [10.0, 20.0]
    # B has no Q2 score -> null-padded across every metric, residual included.
    assert series["B"]["risk_score"] == [50.0, None]
    assert series["B"]["risk_residual"] == [10.0, None]
    assert series["B"]["accountability_gap"] == [5.0, None]


def test_assemble_omits_residual_and_unpredicted_tracts():
    quarters = ["2024Q1"]
    scored = {"2024Q1": _scored({"A": 80.0})}
    # with_residual False -> no risk_residual key at all.
    series = lg._assemble(quarters, scored, predicted={}, with_residual=False)
    assert "risk_residual" not in series["A"]
    assert set(series["A"]) == {
        "quarters", "risk_score", *lg.COMPONENT_COLS}

    # with_residual True but tract absent from the baseline model -> null residual.
    series2 = lg._assemble(quarters, scored, predicted={}, with_residual=True)
    assert series2["A"]["risk_residual"] == [None]


# ── End-to-end loop with the scoring step stubbed ────────────────────────────

def test_build_timeseries_stubbed(monkeypatch):
    """Drive build_timeseries without touching Socrata/geopandas: stub the
    load/join/score helpers so the orchestration + schema are exercised."""
    monkeypatch.setattr(lg, "load_tracts", lambda: "TRACTS")
    monkeypatch.setattr(lg, "load_acs", lambda: "ACS")
    monkeypatch.setattr(lg, "load_pluto", lambda: "PLUTO")
    monkeypatch.setattr(lg, "join_pluto_to_tracts", lambda p, t: "PLUTO_JOINED")

    # Each period returns deterministic scores keyed off the start date so we can
    # assert the windows were distinct.
    by_start = {
        "2024-01-01": _scored({"A": 60.0, "B": 40.0}),
        "2024-04-01": _scored({"A": 65.0, "B": 35.0}),
    }
    captured: list[tuple[str, str]] = []

    def fake_score(tracts, acs, joined_pluto, start, end, *, borough=None, verbose=False):
        captured.append((start, end))
        return by_start[start]

    monkeypatch.setattr(lg, "score_period", fake_score)
    monkeypatch.setattr(
        lg, "_baseline_predictions",
        lambda *a, **k: {"A": 50.0, "B": 50.0},
    )

    series = lg.build_timeseries(["2024Q1", "2024Q2"])

    assert captured == [("2024-01-01", "2024-04-01"), ("2024-04-01", "2024-07-01")]
    assert series["A"]["risk_score"] == [60.0, 65.0]
    assert series["A"]["risk_residual"] == [10.0, 15.0]
    assert series["B"]["risk_score"] == [40.0, 35.0]


def test_build_timeseries_rolling_widens_windows(monkeypatch):
    monkeypatch.setattr(lg, "load_tracts", lambda: None)
    monkeypatch.setattr(lg, "load_acs", lambda: None)
    monkeypatch.setattr(lg, "load_pluto", lambda: None)
    monkeypatch.setattr(lg, "join_pluto_to_tracts", lambda p, t: None)

    captured: list[tuple[str, str]] = []

    def fake_score(tracts, acs, joined_pluto, start, end, *, borough=None, verbose=False):
        captured.append((start, end))
        return _scored({"A": 1.0})

    monkeypatch.setattr(lg, "score_period", fake_score)

    lg.build_timeseries(["2024Q4"], rolling=4, with_residual=False)
    assert captured == [("2024-01-01", "2025-01-01")]  # trailing 4Q = full year
