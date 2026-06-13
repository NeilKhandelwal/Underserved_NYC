"""SPIKE — quarterly longitudinal scoring from the NYC Open Data (Socrata) API.

Proof-of-concept for two proposed changes (see docs/longitudinal-design.md):

  1. Build-time API fetch — pull *filtered* records from Socrata instead of
     reading the ~13 GB 311 CSV and the ~1.3 GB HPD CSV from data/. Server-side
     `$where`/`$select` cut the transfer to a targeted slice.
  2. Longitudinal scoring — bucket the fetched records into quarters and run the
     EXISTING scoring kernel (`pipeline.aggregate.aggregate` +
     `pipeline.regression.run_rank_composite`) once per quarter, producing a
     per-tract quarterly `risk_score` time series.

Deliberately narrow for a spike: one borough (default Bronx), a few recent
quarters. It exercises the real pipeline functions unchanged.

What this spike does NOT cover (documented in the design doc, not built here):
  - Vacate orders are held empty (rare; doesn't change rank order). Production
    would fetch them from their own Socrata dataset.
  - ACS demographics are loaded once (2022 vintage) and held constant — the
    composite `risk_score` doesn't use them; the RF *residual* does, and is
    out of scope for this spike.
  - Percentiles here are within the fetched borough set; production scores
    across all tracts citywide.

Run:
    python scripts/spike_quarterly.py                      # Bronx, 2024 Q1-Q3
    python scripts/spike_quarterly.py --quarters 2024Q1 2024Q2 --max-pages 1
    SOCRATA_APP_TOKEN=xxxx python scripts/spike_quarterly.py   # higher rate limit
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys
from pathlib import Path

# Allow `python scripts/spike_quarterly.py` to import the pipeline package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import geopandas as gpd
import pandas as pd
import requests

from pipeline.load_and_clean import (
    HOUSING_COMPLAINT_TYPES,
    _filter_to_nyc,
    load_tracts,
)
from pipeline.aggregate import aggregate
from pipeline.regression import run_rank_composite
from pipeline.spatial_join import (
    join_311_to_tracts,
    join_hpd_to_tracts,
    join_vacate_to_tracts,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOCRATA = "https://data.cityofnewyork.us/resource"
DATASET_311 = "erm2-nwe9"   # 311 Service Requests (2020-present)
DATASET_HPD = "wvxf-dwi5"   # Housing Maintenance Code Violations
DATASET_PLUTO = "64uk-42ks"  # PLUTO (for HPD bbl -> lat/lon; HPD API has no lat/lon)

# Socrata borough spellings differ per dataset.
BORO_311 = {"BRONX": "BRONX", "BROOKLYN": "BROOKLYN", "MANHATTAN": "MANHATTAN",
            "QUEENS": "QUEENS", "STATEN ISLAND": "STATEN ISLAND"}
BORO_PLUTO = {"BRONX": "BX", "BROOKLYN": "BK", "MANHATTAN": "MN",
              "QUEENS": "QN", "STATEN ISLAND": "SI"}


@contextlib.contextmanager
def quiet():
    """Silence the chatty pipeline internals so the spike output stays readable."""
    with contextlib.redirect_stdout(io.StringIO()):
        yield


def socrata_fetch(dataset: str, select: str, where: str, *, order: str,
                  app_token: str | None, max_pages: int, page: int = 50000) -> pd.DataFrame:
    """Paged Socrata pull. Returns a DataFrame of the selected columns."""
    rows: list[dict] = []
    headers = {"X-App-Token": app_token} if app_token else {}
    for i in range(max_pages):
        params = {"$select": select, "$where": where, "$order": order,
                  "$limit": page, "$offset": i * page}
        r = requests.get(f"{SOCRATA}/{dataset}.json", params=params,
                         headers=headers, timeout=120)
        r.raise_for_status()
        batch = r.json()
        rows.extend(batch)
        if len(batch) < page:
            break
    return pd.DataFrame(rows)


def fetch_311(boro: str, start: str, end: str, **kw) -> pd.DataFrame:
    types = ",".join("'" + t.replace("'", "''") + "'" for t in sorted(HOUSING_COMPLAINT_TYPES))
    where = (f"created_date >= '{start}' AND created_date < '{end}' "
             f"AND borough = '{BORO_311[boro]}' AND complaint_type in ({types})")
    df = socrata_fetch(
        DATASET_311,
        select="unique_key,complaint_type,created_date,closed_date,latitude,longitude",
        where=where, order="created_date", **kw,
    )
    print(f"  311:   fetched {len(df):,} rows")
    return df


def fetch_hpd(boro: str, start: str, end: str, **kw) -> pd.DataFrame:
    where = (f"class = 'C' AND boro = '{boro}' "
             f"AND inspectiondate >= '{start}' AND inspectiondate < '{end}'")
    df = socrata_fetch(
        DATASET_HPD, select="class,inspectiondate,boroid,block,lot",
        where=where, order="inspectiondate", **kw,
    )
    print(f"  HPD:   fetched {len(df):,} rows")
    return df


def fetch_pluto_bbl(boro: str, **kw) -> dict[str, tuple[float, float]]:
    """bbl -> (lat, lon), used to geocode HPD violations (API HPD has no lat/lon)."""
    df = socrata_fetch(
        DATASET_PLUTO, select="bbl,latitude,longitude",
        where=f"borough = '{BORO_PLUTO[boro]}'", order="bbl", **kw,
    )
    out: dict[str, tuple[float, float]] = {}
    for bbl, lat, lon in df[["bbl", "latitude", "longitude"]].itertuples(index=False):
        try:
            out[str(int(float(bbl)))] = (float(lat), float(lon))
        except (TypeError, ValueError):
            continue
    print(f"  PLUTO: {len(out):,} bbl->lat/lon entries")
    return out


ACS_COLS = ["median_income", "mean_commute_time", "population", "housing_units",
            "poverty_rate", "pct_black", "pct_hispanic", "pct_foreign_born",
            "rent_burden", "unemployment_rate", "pct_bachelors"]


def acs_from_bundle() -> pd.DataFrame:
    """Demographics from the already-built serving bundle instead of a live
    Census call. ACS is slow-changing and held constant across quarters here;
    the composite risk_score doesn't use it (only the out-of-scope RF residual
    does), but aggregate() requires population/housing_units to be present."""
    path = PROJECT_ROOT / "serving" / "data" / "tracts.json"
    if not path.exists():
        sys.exit(f"{path} missing — run `make serving-bundle` first.")
    records = json.load(open(path))
    rows = [{"GEOID": str(g), **{c: r.get(c) for c in ACS_COLS}}
            for g, r in records.items()]
    return pd.DataFrame(rows)


def _quarter_bounds(label: str) -> tuple[str, str]:
    year, q = int(label[:4]), int(label[-1])
    starts = {1: f"{year}-01-01", 2: f"{year}-04-01", 3: f"{year}-07-01", 4: f"{year}-10-01"}
    ends = {1: f"{year}-04-01", 2: f"{year}-07-01", 3: f"{year}-10-01", 4: f"{year + 1}-01-01"}
    return starts[q], ends[q]


def points_gdf(df: pd.DataFrame, lat_col: str, lon_col: str) -> gpd.GeoDataFrame:
    df = df.copy()
    df[lat_col] = pd.to_numeric(df[lat_col], errors="coerce")
    df[lon_col] = pd.to_numeric(df[lon_col], errors="coerce")
    df = _filter_to_nyc(df, lat_col, lon_col)
    return gpd.GeoDataFrame(
        df, geometry=gpd.points_from_xy(df[lon_col], df[lat_col]), crs="EPSG:4326"
    )


def prep_311_quarter(df_311: pd.DataFrame, start: str, end: str) -> gpd.GeoDataFrame:
    """Slice to the quarter and reproduce load_311's closure-time contract."""
    df = df_311.copy()
    df["created"] = pd.to_datetime(df["created_date"], errors="coerce")
    df["closed"] = pd.to_datetime(df["closed_date"], errors="coerce")
    df = df[(df["created"] >= start) & (df["created"] < end)]
    df["closure_time_days"] = (df["closed"] - df["created"]).dt.total_seconds() / 86400
    df = df.dropna(subset=["closure_time_days", "complaint_type"])
    df = df[df["closure_time_days"] >= 0.04]
    return points_gdf(df[["complaint_type", "closure_time_days", "latitude", "longitude"]],
                      "latitude", "longitude")


def prep_hpd_quarter(df_hpd: pd.DataFrame, bbl_map: dict, start: str, end: str) -> gpd.GeoDataFrame:
    """Slice to the quarter, build BBL, geocode via PLUTO, return points."""
    df = df_hpd.copy()
    df["inspected"] = pd.to_datetime(df["inspectiondate"], errors="coerce")
    df = df[(df["inspected"] >= start) & (df["inspected"] < end)].dropna(subset=["inspected"])

    lats, lons = [], []
    for boroid, block, lot in df[["boroid", "block", "lot"]].itertuples(index=False):
        try:
            ll = bbl_map.get(f"{int(boroid)}{int(block):05d}{int(lot):04d}")
        except (TypeError, ValueError):
            ll = None
        lats.append(ll[0] if ll else None)
        lons.append(ll[1] if ll else None)
    df["latitude"], df["longitude"] = lats, lons
    df = df.dropna(subset=["latitude", "longitude"])
    return points_gdf(df[["latitude", "longitude"]], "latitude", "longitude")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--borough", default="BRONX", choices=list(BORO_311))
    ap.add_argument("--quarters", nargs="+", default=["2024Q1", "2024Q2", "2024Q3"])
    ap.add_argument("--max-pages", type=int, default=20,
                    help="cap pages per source (50k rows/page); lower = faster smoke test")
    ap.add_argument("--out", type=Path, default=PROJECT_ROOT / "output" / "spike_quarterly.json")
    args = ap.parse_args()
    token = os.environ.get("SOCRATA_APP_TOKEN")
    fetch_kw = dict(app_token=token, max_pages=args.max_pages)

    bounds = {q: _quarter_bounds(q) for q in args.quarters}
    span_start = min(s for s, _ in bounds.values())
    span_end = max(e for _, e in bounds.values())
    print(f"Borough {args.borough} | quarters {args.quarters} | span {span_start}..{span_end}"
          f"{' | app token' if token else ' | NO app token (lower rate limit)'}")

    print("Fetching from Socrata (build-time API — replaces the 13 GB + 1.3 GB CSVs):")
    df_311 = fetch_311(args.borough, span_start, span_end, **fetch_kw)
    df_hpd = fetch_hpd(args.borough, span_start, span_end, **fetch_kw)
    bbl_map = fetch_pluto_bbl(args.borough, **fetch_kw)
    if df_311.empty:
        sys.exit("No 311 rows fetched — check connectivity / filters.")

    print("Loading tracts + ACS (demographics from the serving bundle, held constant)...")
    with quiet():
        tracts = load_tracts()
    acs = acs_from_bundle()
    empty_vacate = gpd.GeoDataFrame(
        {"GEOID": pd.Series(dtype=str), "vacated_units": pd.Series(dtype=float)},
        geometry=gpd.GeoSeries([], crs="EPSG:4326"),
    )

    series: dict[str, dict[str, float]] = {}
    print("\nPer-quarter scoring (reuses pipeline.aggregate + run_rank_composite):")
    for q in args.quarters:
        start, end = bounds[q]
        with quiet():
            g311 = join_311_to_tracts(prep_311_quarter(df_311, start, end), tracts)
            ghpd = join_hpd_to_tracts(prep_hpd_quarter(df_hpd, bbl_map, start, end), tracts)
        if len(g311) < 50:
            print(f"  {q}: only {len(g311)} 311 records joined — skipping "
                  "(raise --max-pages or widen the window).")
            continue
        with quiet():
            gvac = join_vacate_to_tracts(empty_vacate, tracts) if len(empty_vacate) else empty_vacate
            tract_df = aggregate(tracts, g311, ghpd, gvac, acs).reset_index(drop=True)
            scores, _ = run_rank_composite(tract_df)
            tract_df.loc[scores.index, "risk_score"] = scores
        scored = tract_df.dropna(subset=["risk_score"])
        for geoid, score in zip(scored["GEOID"], scored["risk_score"]):
            series.setdefault(str(geoid), {})[q] = round(float(score), 2)
        print(f"  {q}: {len(g311):,} 311 + {len(ghpd):,} HPD joined -> {len(scored):,} tracts scored")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(series, f, indent=1)
    print(f"\nWrote {args.out}  ({len(series):,} tracts)")

    # Show a few tracts that appear in every quarter, to illustrate the trend.
    complete = {g: v for g, v in series.items() if len(v) == len(args.quarters)}
    print(f"\nExample quarterly trends ({len(complete):,} tracts present in all quarters):")
    print(f"  {'GEOID':<12} " + "  ".join(f"{q:>7}" for q in args.quarters) + "   trend")
    for geoid in list(complete)[:6]:
        vals = [complete[geoid][q] for q in args.quarters]
        arrow = "↑" if vals[-1] > vals[0] + 1 else "↓" if vals[-1] < vals[0] - 1 else "→"
        print(f"  {geoid:<12} " + "  ".join(f"{v:7.1f}" for v in vals) + f"   {arrow} {vals[-1] - vals[0]:+.1f}")


if __name__ == "__main__":
    main()
