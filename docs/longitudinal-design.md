# Design: Longitudinal Trends + Build-Time Socrata Fetch

Status: **in progress.** The spike that de-risked the core
(`scripts/spike_quarterly.py`, see [Spike](#spike)) is now being landed section by
section:

- [x] §1 Data layer — `pipeline/sources/socrata.py` + API-backed loaders
- [x] §2 Quarterly scoring loop — `pipeline/longitudinal.py` → `output/timeseries.json`
- [x] §3 Bundle schema — `build_serving_bundle.py` copies `timeseries.json` (optional)
- [x] §4 API — `store` loads it; `GET /api/tract/{geoid}/timeseries`
- [ ] §5 Frontend — per-tract sparkline + Watchlist trend arrow

## Motivation

Today the tool is a single snapshot: 311 is hardcoded to `>= 2024`
(`pipeline/load_and_clean.py`), HPD/vacate aren't date-filtered, ACS is pinned to
2022, and `pipeline/score.py` emits one `risk_score` per tract. We want two things:

1. **Longitudinal** — a `risk_score` (and components) per tract **per quarter**, so
   the UI can answer "is this tract's neglect rising or falling?"
2. **Build-time API fetch** — pull *filtered* records from NYC Open Data (Socrata)
   instead of reading the ~13 GB 311 CSV and ~1.3 GB HPD CSV from `data/`. This
   removes the heavy local dependency and makes the pipeline reproducible anywhere.

The deployed app is unaffected in shape: it still serves a small pre-baked bundle.

## Why this is low-risk (proven in the spike)

- The scoring kernel already runs on a date-sliced subset:
  `validation/test_temporal_split.py` calls `aggregate()` + `run_rank_composite()`
  on pre-cutoff data. The longitudinal loop is just "do that once per quarter."
- Socrata supports server-side `$where` (date + complaint type + borough) and
  `$select` (column projection), so the transfer shrinks from tens of GB to a
  targeted slice. The spike fetched a full Bronx quarter of housing 311 in ~120k
  rows.
- HPD violations on Socrata (`wvxf-dwi5`) have **no lat/lon** (unlike the local
  CSV). The spike resolves this by geocoding via a PLUTO `bbl → lat/lon` lookup
  (`64uk-42ks`), built from `boroid`/`block`/`lot`. This is the one non-obvious
  finding the spike surfaced.

## Architecture

### 1. Data layer — `pipeline/sources/socrata.py` (new)

A small paged client `fetch(dataset_id, select, where, order, app_token) -> DataFrame`
with an on-disk cache (`data/cache/<dataset>_<hash>.parquet`) so re-runs and
multiple quarters don't re-pull. Then rewrite the loaders to be API-backed while
preserving their **existing output contract** so `spatial_join`/`aggregate` are
untouched:

- `load_311(start, end, borough=None)` → GeoDataFrame `[complaint_type, closure_time_days, geometry]`
  (dataset `erm2-nwe9`; note the boundary: 2020+ is `erm2-nwe9`, pre-2020 is `fhrw-4uyv`).
- `load_hpd(start, end, borough=None)` → GeoDataFrame `[geometry]`, Class C only,
  geocoded by BBL via PLUTO (`wvxf-dwi5` + `64uk-42ks`).
- `load_vacate(start, end)` → GeoDataFrame `[vacated_units, geometry]` from the
  vacate-orders dataset (small; the spike holds this empty).

Set `SOCRATA_APP_TOKEN` for a higher rate limit.

### 2. Quarterly scoring loop — `pipeline/longitudinal.py` (new)

```
for q in quarters(start, end):
    slice each source to [q.start, q.end)
    join_*_to_tracts(...)            # unchanged
    aggregate(...)                   # unchanged
    run_rank_composite(...)          # unchanged
    collect per-tract: risk_score + the 4 raw components
```

Decisions:

- **Demographics (ACS) / building stock (PLUTO):** hold at the nearest available
  vintage per year (or a fixed baseline). The composite `risk_score` doesn't use
  them; only the RF **residual** does — so for the residual, apply **one fixed
  demographic model** across quarters (don't retrain per quarter), so residual
  *trends* reflect service change, not model drift. (The spike sources ACS from
  the existing serving bundle, held constant — same idea.)
- **Comparability:** percentile `risk_score` is within-period by construction
  (`run_rank_composite` uses `.rank(pct=True)`), so the quarterly score is a tract's
  *relative rank that quarter* — ideal for "is relative neglect rising?". Also store
  the **raw components** (`accountability_gap`, rates), which ARE absolute-comparable
  across quarters, so a trend chart can show both relative rank and absolute level.
- **Noise:** quarterly per-tract counts are small and noisy. Offer a **rolling
  4-quarter** window option in addition to discrete quarters.

### 3. Bundle schema — additive, back-compatible

Add an optional `serving/data/timeseries.json`:

```json
{ "<GEOID>": { "quarters": ["2024Q1", ...],
               "risk_score": [..], "risk_residual": [..],
               "accountability_gap": [..] } }
```

Keep `tracts.json` as the **latest quarter** so the current map/UI keep working
unchanged. `scripts/build_serving_bundle.py` copies `timeseries.json` if present
(the same optional-artifact pattern already used for the district overlay and the
planned RAG index).

### 4. API — `api/`

- `store.load()` reads `timeseries.json` into a GEOID-keyed dict (alongside `tracts`).
- New `GET /api/tract/{geoid}/timeseries` → `TractTimeSeries` (or an optional
  `time_series` field on `TractDetail`). Keyed by GEOID, mirrors the JSON above.
- Watchlist could gain a `trend` (latest − earliest) for sorting "fastest-worsening".

### 5. Frontend — per-tract trend charts (the chosen UX; **no map/tile changes**)

Reuse the hand-rolled SVG plot already in `frontend/src/components/Demographics.tsx`
to add:
- a quarterly **sparkline** of `risk_score` (or residual) to `DetailCard.tsx`, and
- a **trend arrow + delta** in the Watchlist drilldown.

The choropleth keeps coloring from the baked PMTiles (latest quarter). Animating
the *map* over time is explicitly deferred — it would require per-period tiles or
refactoring `MapView` to color from `/api` at runtime.

## Spike

`scripts/spike_quarterly.py` (runnable) proves the chain end-to-end on a narrow
slice (default Bronx, 2024 Q1–Q3):

- Fetches 311 + HPD + PLUTO from Socrata (no local heavy CSVs), geocodes HPD by BBL.
- Buckets into quarters and runs the unchanged `aggregate()` + `run_rank_composite()`.
- Writes `output/spike_quarterly.json` = `{GEOID: {quarter: risk_score}}` and prints
  example tracts whose score moves across quarters.

Run:
```bash
python scripts/spike_quarterly.py                          # Bronx, 2024 Q1-Q3
python scripts/spike_quarterly.py --quarters 2024Q1 2024Q2 --max-pages 3   # quick
SOCRATA_APP_TOKEN=xxxx python scripts/spike_quarterly.py   # higher rate limit
```

Spike simplifications (documented; addressed in the full design above): vacate held
empty, ACS from the bundle held constant, percentiles within the fetched borough
only, RF residual out of scope.

## Risks / open questions

- **Volume & rate limits** — multi-year, all-borough pulls are large; use an app
  token, the on-disk cache, and chunk by quarter. Pre-2020 needs the second 311
  dataset (`fhrw-4uyv`).
- **HPD geocoding coverage** — BBLs not present in PLUTO drop out; measure the match
  rate and consider a geocoder fallback.
- **Quarterly noise** — small counts; rolling windows mitigate.
- **Comparability interpretation** — be explicit in the UI that the line is *relative
  rank* unless showing the raw-component view.
- **Build time** — scales with quarter count × sources; the cache makes re-runs cheap.
