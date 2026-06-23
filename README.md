# NYC Underservice Risk Index

An interactive map and API that quantify housing-service underservice across every NYC census tract. The map identifies tracts where measured underservice exceeds what poverty, race, and demographics alone predict. That unexplained residual is the signal of interest: it is more likely to reflect agency routing, inspection gaps, and institutional responsiveness than the composition of who lives there.

**Live:** [underserved-nyc.fly.dev](https://underserved-nyc.fly.dev)

---

## What it does

Most "underserved neighborhood" maps track demographics and poverty: low-income, majority-minority areas score worst. That pattern is real but expected, and it is not locally actionable. This project separates the **structural** pattern from the **institutional** one:

1. It builds a 0–100 **Underservice Risk Score** for all ~2,200 NYC census tracts from housing-stress signals (311 closure times, HPD violations, vacate orders), after normalizing out complaint-filing bias and HPD triage.
2. It trains a Random Forest to predict the risk score from demographics and building age, then takes the **residual** (actual − predicted). A high positive residual marks a tract receiving worse service than its demographics alone would predict.
3. It exposes the result as an explorable map, a ranked watchlist with per-tract explanations, and a JSON API.

The residuals still cluster geographically (Moran's I ≈ +0.19), consistent with service patterns following institutional geography rather than tract demographics.

> **What it is not:** a screening and prioritization tool, not proof of causation. A high residual warrants investigation, not a verdict. See [Methodology](#methodology) and [MATH.md](MATH.md) for the limits.

---

## Project scope

| In scope | Out of scope |
|---|---|
| Housing-service underservice (311 / HPD / vacate orders) | Non-housing services (sanitation, policing, schools) |
| Census-tract granularity, citywide (all 5 boroughs) | Building- or address-level claims |
| Per-tract quarterly trends (2024–present) | Forecasting or projection of future risk |
| Surfacing *where* service lags its prediction | Asserting *why* (causal attribution) |

The intended audience is twofold: civic-tech and policy users triaging where to look, and engineers evaluating the project as an end-to-end build (data pipeline → ML → API → map UI → deploy).

---

## Features

**Map** — A MapLibre choropleth of all tracts with switchable overlays: the risk score, the **unexplained-underservice residual** (diverging red/green), the model's predicted risk, and individual demographic layers (income, poverty, race, rent burden, and others). A toggle overlays **City Council district** boundaries with district numbers. Clicking a tract opens a detail card showing its score, residual, district, a quarterly trend sparkline, and how its key metrics compare to the citywide average.

**Watchlist** — A ranked table of residual outliers in three modes: *most unexplained underservice*, *unexpected success* (better-served than predicted), and *biggest surprises*. Each row expands into a per-tract drilldown — a plain-language headline (e.g. *"scores +18 points vs. demographic prediction; main driver: accountability gap 3.2× city average"*), the four risk components vs. citywide, and a demographics snapshot. A view toggle aggregates the same data by **neighborhood** or **council district** so it reads as areas needing attention rather than 2,200 individual rows.

**Demographics** — Correlations between each demographic and building feature and the risk score, with an interactive scatterplot per feature.

**Predictor** — A what-if panel: adjust demographic sliders and watch the Random Forest's predicted risk update live.

**Ask** *(coming soon)* — A planned assistant for "what policies or factors could explain this outlier?", grounded in the tool's tract data, cited web search, and housing-policy documents.

**API** — Every value the UI uses is available as a public JSON endpoint (see [API](#api)).

---

## How it works

```
data/ (16 GB, gitignored)
  └─▶ pipeline/  ───▶ output/ (master.geojson, demographic_model.joblib, demographic_model.json)
                          │
                          └─▶ scripts/build_serving_bundle.py ──▶ serving/
                                  (tracts.json incl. centroids, citywide_stats.json,
                                   timeseries.json, demographic_model.{joblib,json},
                                   tracts.pmtiles via tippecanoe, districts.geojson)
                                                   │
                                                   ▼
                                             api/ (FastAPI)
                                              ├─ /api/{tract,tracts,watchlist,districts,
                                              │   correlations,scatter,model,overlays,predict}
                                              ├─ /api/tract/{geoid}/timeseries
                                              ├─ /healthz
                                              ├─ /tiles  (StaticFiles — PMTiles + district overlay, Range-capable)
                                              └─ /       (built SPA, mounted LAST)
```

Three stages:

1. **Pipeline** (`pipeline/`, geopandas + scikit-learn) ingests the raw datasets, normalizes confounds, builds the composite risk score, trains the Random Forest, and computes cross-validated residuals into `output/`.
2. **Serving-bundle build** (`scripts/build_serving_bundle.py`, **stdlib-only**) extracts only what the API needs — per-tract records, citywide stats, the model, and `tippecanoe` vector tiles — into a ~21 MB `serving/` bundle. Council districts are joined here too (`scripts/patch_council_districts.py`), without a pipeline re-run.
3. **API + SPA** (`api/`, FastAPI + a Vite/React/MapLibre frontend) serves the bundle. The production image installs only `requirements-api.txt` — no geopandas, no raw data — so it stays small.

The **build/serve split** is the central design decision: the heavy, dependency-laden computation runs once, offline; the deployed container only reads pre-baked artifacts.

For the full statistical methodology (every normalization, the model, and the validation suite), see **[MATH.md](MATH.md)**.

---

## Quick Start

```bash
# Clone and install
git clone https://github.com/NeilKhandelwal/Underserved_NYC.git
cd Underserved_NYC

python -m venv .venv && source .venv/bin/activate
make install-dev          # API + test/lint deps

# Frontend
cd frontend && npm install && cd ..

# Build the serving bundle (needs output/ artifacts + tippecanoe)
make serving-bundle

# Run locally
make api &                # FastAPI on :8000
make frontend-dev         # Vite dev server on :5173 (proxies /api, /tiles)
```

Open <http://localhost:5173>.

---

## API

All endpoints are under `/api` and return JSON.

| Endpoint | Returns |
|---|---|
| `GET /api/tracts` | Lightweight list of every tract (id, name, borough, district, score, residual) |
| `GET /api/tract/{geoid}` | Full detail: score, residual, band, metric-vs-city comparisons, interpretation |
| `GET /api/tract/{geoid}/timeseries` | Per-tract quarterly risk-score history (drives the trend sparkline) |
| `GET /api/watchlist` | Top residual outliers (`direction`, `borough`, `district`, `n`) |
| `GET /api/watchlist/groups` | Watchlist aggregated `by=neighborhood\|council_district` |
| `GET /api/districts` | Distinct City Council district numbers |
| `GET /api/overlays` | Map overlay definitions + residual color bins |
| `GET /api/correlations` | Pearson r of each feature vs. the risk score |
| `GET /api/scatter/{feature}` | Per-tract points for a feature-vs-score scatterplot |
| `GET /api/model` | Random Forest metadata (R², RMSE, feature importances, slider ranges) |
| `POST /api/predict` | Predicted risk for a hypothetical tract from demographic inputs |
| `GET /healthz` | Liveness + tract/model load status |

---

## Deploy (Docker + Fly.io)

```bash
# Build & run locally
docker buildx build -t underserved-nyc .
docker run -p 8080:8080 underserved-nyc
# → http://localhost:8080/healthz

# Deploy to Fly.io
fly launch          # first time (uses fly.toml)
fly deploy          # subsequent deploys
```

The multi-stage `Dockerfile`:
1. **Stage 1** — `node:22-slim` builds `frontend/dist`
2. **Stage 2** — `python:3.13-slim` + tippecanoe regenerates the serving bundle from `output/`
3. **Stage 3** — production image: installs `requirements-api.txt`, copies API + frontend + serving bundle, runs uvicorn on port 8080

---

## Development

| Command | Purpose |
|---------|---------|
| `make api` | FastAPI on :8000 (auto-reload) |
| `make frontend-dev` | Vite dev server on :5173 |
| `make test` | pytest (46 tests across api, sources, longitudinal, and bundle) |
| `make lint` | ruff check |
| `make frontend-build` | TypeScript + Vite production build |
| `make serving-bundle` | Regenerate serving/ from output/ |
| `make timeseries` | Build output/timeseries.json — per-tract quarterly risk scores |
| `make patch-districts` | Join council districts onto output/master.geojson (no pipeline re-run) |
| `make artifacts` | Full pipeline rebuild (~15 min, needs data/) |

---

## Data Sources

| Source | Used For |
|--------|----------|
| NYC 311 Service Requests (2024+) | Closure-time signal, complaint rates |
| HPD Class C Violations | Severity signal — most serious housing code violations |
| HPD Vacate Orders | Severity weighting — uninhabitable buildings |
| ACS 2022 5-Year Estimates | Demographics + denominators (14 variables) |
| NYC 2020 Census Tract Boundaries | Spatial unit of analysis |
| NYC PLUTO | Building-stock features (year built, rent stabilization proxy) |
| [NYC City Council Districts](https://data.cityofnewyork.us/resource/872g-cjhh.geojson) (`data/nycc.geojson`) | District tagging + map overlay (`make patch-districts`) |

---

## Methodology

The index decomposes underservice into two components:

1. **Structural** — the citywide pattern in which low-income, majority-minority neighborhoods receive worse service. Real but expected.
2. **Institutional (residual)** — tracts receiving worse service than *even the structural pattern predicts*. This is the actionable signal.

Steps:
1. Build a composite risk score from independent housing-stress signals (311 closure times, HPD violations, vacate orders), first normalizing out complaint-type, income-filing bias, and HPD triage.
2. Train a Random Forest baseline predicting risk from ACS demographics and PLUTO building stock.
3. Compute the residual: actual risk − predicted risk. A positive residual is underservice that demographics alone do not explain.

A validation suite (temporal split, bootstrap CIs, weight-sensitivity, and Moran's I spatial autocorrelation) checks that the score is predictive and robust. For the full statistical methodology, see [MATH.md](MATH.md).

---

## License

[MIT](LICENSE)