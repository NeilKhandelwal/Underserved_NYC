# NYC Underservice Risk Index — developer & build tasks.
# Run `make help` for the list.

PY  := .venv/bin/python
PIP := .venv/bin/pip

.DEFAULT_GOAL := help
.PHONY: help install install-pipeline install-api artifacts serving-bundle validate app clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

install: ## Install full local dev stack (pipeline + Streamlit app)
	$(PIP) install -r requirements.txt

install-pipeline: ## Install only the batch pipeline + validation deps
	$(PIP) install -r requirements-pipeline.txt

install-api: ## Install only the light production serving deps
	$(PIP) install -r requirements-api.txt

artifacts: ## Rebuild master.geojson + model from raw data (needs data/, ~5-15 min)
	$(PY) -m pipeline.score
	$(PY) -m pipeline.demographic_analysis

serving-bundle: ## Build the deployable serving/ bundle from existing artifacts (fast)
	$(PY) scripts/build_serving_bundle.py

validate: ## Run the statistical validation suite
	$(PY) -m validation.run_all

app: ## Run the current Streamlit app
	.venv/bin/streamlit run app.py

clean: ## Remove the generated serving bundle
	rm -rf serving/data serving/tiles
