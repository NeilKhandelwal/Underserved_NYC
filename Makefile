# NYC Underservice Risk Index — developer & build tasks.
# Run `make help` for the list.

PY  := .venv/bin/python
PIP := .venv/bin/pip

.DEFAULT_GOAL := help
.PHONY: help install install-pipeline install-api install-dev artifacts serving-bundle patch-districts validate app api test lint frontend-install frontend-dev frontend-build clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

install: ## Install full local dev stack (pipeline + Streamlit app)
	$(PIP) install -r requirements.txt

install-pipeline: ## Install only the batch pipeline + validation deps
	$(PIP) install -r requirements-pipeline.txt

install-api: ## Install only the light production serving deps
	$(PIP) install -r requirements-api.txt

install-dev: ## Install serving deps + test/lint tooling
	$(PIP) install -r requirements-dev.txt

artifacts: ## Rebuild master.geojson + model from raw data (needs data/, ~5-15 min)
	$(PY) -m pipeline.score
	$(PY) -m pipeline.demographic_analysis

serving-bundle: ## Build the deployable serving/ bundle from existing artifacts (fast)
	$(PY) scripts/build_serving_bundle.py

patch-districts: ## Join City Council districts onto output/master.geojson (needs data/nycc.geojson)
	$(PY) scripts/patch_council_districts.py

validate: ## Run the statistical validation suite
	$(PY) -m validation.run_all

app: ## Run the current Streamlit app
	.venv/bin/streamlit run app.py

api: ## Run the FastAPI serving layer (http://127.0.0.1:8000, /docs for Swagger)
	.venv/bin/uvicorn api.main:app --reload --port 8000

test: ## Run the API test suite
	$(PY) -m pytest tests/ -q

lint: ## Lint api/, tests/, scripts/
	.venv/bin/ruff check api/ tests/ scripts/

frontend-install: ## Install frontend npm dependencies
	cd frontend && npm install

frontend-dev: ## Run the Vite dev server (proxies /api + /tiles to :8000)
	cd frontend && npm run dev

frontend-build: ## Build the frontend to frontend/dist (served by `make api` in prod)
	cd frontend && npm run build

clean: ## Remove the generated serving bundle + frontend build
	rm -rf serving/data serving/tiles frontend/dist
