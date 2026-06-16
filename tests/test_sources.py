"""Unit tests for the build-time data layer (pipeline/sources + API-backed
loaders). All network is mocked — these run offline in CI."""
from __future__ import annotations

import pandas as pd
import pytest
import requests

from pipeline import load_and_clean as lc
from pipeline.sources import census, socrata


class FakeResp:
    def __init__(self, payload, *, status=200, ctype="application/json", url="https://x"):
        self._payload = payload
        self.status_code = status
        self.headers = {"content-type": ctype}
        self.url = url
        self.text = payload if isinstance(payload, str) else ""

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))

    def json(self):
        if isinstance(self._payload, str):
            raise ValueError("not json")
        return self._payload


# ── Socrata client ───────────────────────────────────────────────────────────

def test_in_list_quotes_and_escapes():
    assert socrata.in_list(["A", "B"]) == "'A','B'"
    assert socrata.in_list(["O'Brien"]) == "'O''Brien'"


def test_socrata_cache_miss_then_hit(tmp_path, monkeypatch):
    monkeypatch.setattr(socrata, "CACHE_DIR", tmp_path)
    calls = {"n": 0}

    def fake_get(url, params=None, headers=None, timeout=None):
        calls["n"] += 1
        return FakeResp([{"a": "1"}, {"a": "2"}])

    monkeypatch.setattr(socrata.requests, "get", fake_get)
    df1 = socrata.fetch("ds", select="a", where="1=1", order="a", page_size=1000)
    assert calls["n"] == 1 and list(df1["a"]) == ["1", "2"]

    df2 = socrata.fetch("ds", select="a", where="1=1", order="a", page_size=1000)
    assert calls["n"] == 1  # served from the parquet cache, no second HTTP call
    assert df1.equals(df2)


def test_socrata_paginates(tmp_path, monkeypatch):
    monkeypatch.setattr(socrata, "CACHE_DIR", tmp_path)

    def fake_get(url, params=None, headers=None, timeout=None):
        offset = params["$offset"]
        # First page full (2 rows), second page short (1 row) -> stop.
        return FakeResp([{"a": "x"}, {"a": "y"}] if offset == 0 else [{"a": "z"}])

    monkeypatch.setattr(socrata.requests, "get", fake_get)
    df = socrata.fetch("ds", select="a", where="1=1", order="a", page_size=2, cache=False)
    assert list(df["a"]) == ["x", "y", "z"]


def test_socrata_retries_then_succeeds(tmp_path, monkeypatch):
    monkeypatch.setattr(socrata, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(socrata.time, "sleep", lambda *_: None)
    seq = [FakeResp("", status=503), FakeResp([{"a": "ok"}])]

    monkeypatch.setattr(socrata.requests, "get",
                        lambda *a, **k: seq.pop(0))
    df = socrata.fetch("ds", select="a", where="1=1", order="a", cache=False)
    assert list(df["a"]) == ["ok"] and not seq


# ── Census client ────────────────────────────────────────────────────────────

def test_census_requires_key(monkeypatch):
    monkeypatch.delenv("CENSUS_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="CENSUS_API_KEY"):
        census.fetch_acs(2022, ["B01003_001E"], cache=False)


def test_census_missing_key_html_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(census, "CACHE_DIR", tmp_path)
    monkeypatch.setenv("CENSUS_API_KEY", "dummy")
    monkeypatch.setattr(census.requests, "get", lambda url, timeout=None: FakeResp(
        "<html>Missing Key</html>", ctype="text/html",
        url="https://api.census.gov/data/missing_key.html"))
    with pytest.raises(RuntimeError, match="non-JSON"):
        census.fetch_acs(2022, ["B01003_001E"])


def test_census_parses_geoid(tmp_path, monkeypatch):
    monkeypatch.setattr(census, "CACHE_DIR", tmp_path)
    monkeypatch.setenv("CENSUS_API_KEY", "dummy")
    payload = [["B01003_001E", "state", "county", "tract"],
               ["1000", "36", "005", "000100"]]
    monkeypatch.setattr(census.requests, "get", lambda url, timeout=None: FakeResp(payload))
    df = census.fetch_acs(2022, ["B01003_001E"])
    assert df["GEOID"].iloc[0] == "36005000100"


# ── API-backed loaders preserve their output contracts ───────────────────────

def test_load_311_contract_and_autoclose(monkeypatch):
    rows = pd.DataFrame([
        {"unique_key": "1", "complaint_type": "HEAT/HOT WATER",
         "created_date": "2024-01-05", "closed_date": "2024-01-08",
         "resolution_description": "Violation issued", "latitude": "40.85", "longitude": "-73.90"},
        {"unique_key": "2", "complaint_type": "PLUMBING",
         "created_date": "2024-01-05", "closed_date": "2024-01-07",
         "resolution_description": "The complaint was closed. NO ACTION taken.",
         "latitude": "40.85", "longitude": "-73.90"},
    ])
    monkeypatch.setattr(lc.socrata, "fetch", lambda *a, **k: rows)
    g = lc.load_311("2024-01-01", "2024-02-01")
    assert set(g.columns) >= {"complaint_type", "closure_time_days", "geometry"}
    assert list(g["complaint_type"]) == ["HEAT/HOT WATER"]  # auto-closed PLUMBING dropped
    assert (g["closure_time_days"] >= 0.04).all()


def test_load_vacate_contract(monkeypatch):
    rows = pd.DataFrame([{"number_of_vacated_units": "3",
                          "latitude": "40.85", "longitude": "-73.90"}])
    monkeypatch.setattr(lc.socrata, "fetch", lambda *a, **k: rows)
    v = lc.load_vacate_orders("2024-01-01", "2024-02-01")
    assert "vacated_units" in v.columns and "geometry" in v.columns
    assert v["vacated_units"].iloc[0] == 3


def test_load_hpd_geocodes_via_pluto(monkeypatch):
    rows = pd.DataFrame([{"class": "C", "inspectiondate": "2024-01-05",
                          "boroid": "2", "block": "2345", "lot": "1"}])
    monkeypatch.setattr(lc.socrata, "fetch", lambda *a, **k: rows)
    monkeypatch.setattr(lc, "_pluto_bbl_latlon", lambda: {"2023450001": (40.85, -73.90)})
    h = lc.load_hpd("2024-01-01", "2024-02-01", borough="BRONX")
    assert "geometry" in h.columns and len(h) == 1
