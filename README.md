# NYC Underservice Risk Index

An interactive map and API that quantifies **municipal neglect** across every NYC census tract — then surfaces the tracts where actual neglect *exceeds* what poverty, race, and demographics alone predict. That unexplained residual is the signal: it likely reflects agency routing decisions, inspection gaps, and political responsiveness rather than who lives there.

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

## Architecture

```
data/ (16 GB, gitignored)
  └─▶ pipeline/  ───▶ output/ (master.geojson, model.joblib, model.json)
                          │
                          └─▶ scripts/build_serving_bundle.py ──▶ serving/
                                  (tracts.json, centroids, citywide_stats.json,
                                   tracts.pmtiles via tippecanoe, model files)
                                                   │
                                                   ▼
                                             api/ (FastAPI)
                                              ├─ /api/{tract,tracts,watchlist,
                                              │   correlations,model,overlays,predict}
                                              ├─ /healthz
                                              ├─ /tiles  (StaticFiles — PMTiles, Range-capable)
                                              └─ /       (built SPA, mounted LAST)
```

The **build/serve split** is the key design decision:
- The **pipeline** (geopandas, libpysal, scikit-learn) produces `output/` from 16 GB of raw data.
- `build_serving_bundle.py` (stdlib-only) extracts only what the API needs into a ~5 MB `serving/` bundle + vector tiles.
- The **production image** installs only `requirements-api.txt` — no geopandas, no raw data.

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
| `make test` | pytest (11 API tests) |
| `make lint` | ruff check |
| `make frontend-build` | TypeScript + Vite production build |
| `make serving-bundle` | Regenerate serving/ from output/ |
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
| [NYC City Council Districts](https://data.cityofnewyork.us/resource/872g-cjhh.geojson) (`data/nycc.geojson`) | District tagging for the Watchlist / detail panel (`make patch-districts`) |

---

## Methodology

The index decomposes underservice into two components:

1. **Structural** — the citywide pattern where low-income, majority-minority neighborhoods receive worse services. Real but not surprising.
2. **Institutional (residual)** — tracts that receive worse service than *even the structural pattern predicts*. This is the actionable signal.

Steps:
1. Build a composite risk score from independent housing-stress signals (311 closure times, HPD violations, vacate orders).
2. Train a Random Forest baseline predicting risk from ACS demographics + PLUTO building stock.
3. Compute the residual: actual risk − predicted risk. Positive residual = neglect that demographics alone don't explain.

For full statistical methodology, see [MATH.md](MATH.md).

---

## License

[MIT](LICENSE)
