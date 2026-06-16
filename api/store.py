"""In-memory data store: loads the serving bundle once at startup.

Holds the per-GEOID records (O(1) lookup), citywide summary stats, the trained
RF model, and a pandas view used for analytics (correlations). None of this
touches the raw data or geopandas.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import joblib
import pandas as pd

from .overlays import OVERLAY_OPTIONS, PRETTY


def _clean(value):
    """Normalize NaN/inf to None so responses serialize as valid JSON."""
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


class DataStore:
    def __init__(self) -> None:
        self.tracts: dict[str, dict] = {}
        self.timeseries: dict[str, dict] = {}
        self.citywide: dict[str, dict] = {}
        self.model = None
        self.model_meta: dict = {}
        self.df: pd.DataFrame | None = None
        self.correlations: list[dict] = []
        self._loaded = False

    @property
    def loaded(self) -> bool:
        return self._loaded

    def load(self, serving_dir: Path) -> None:
        serving_dir = Path(serving_dir)
        with open(serving_dir / "tracts.json") as f:
            raw = json.load(f)
        # Sanitize NaN -> None up front.
        self.tracts = {
            geoid: {k: _clean(v) for k, v in props.items()}
            for geoid, props in raw.items()
        }
        # Per-tract quarterly time series — optional, additive artifact (produced
        # by `python -m pipeline.longitudinal`). Absent in bundles built before the
        # longitudinal loop has run; the timeseries endpoint then 404s per GEOID.
        ts_path = serving_dir / "timeseries.json"
        if ts_path.exists():
            with open(ts_path) as f:
                self.timeseries = json.load(f)
        with open(serving_dir / "citywide_stats.json") as f:
            self.citywide = json.load(f)
        with open(serving_dir / "demographic_model.json") as f:
            self.model_meta = json.load(f)
        self.model = joblib.load(serving_dir / "demographic_model.joblib")

        self.df = pd.DataFrame(list(self.tracts.values()))
        self.correlations = self._compute_correlations()
        self._loaded = True

    def get_tract(self, geoid: str) -> dict | None:
        return self.tracts.get(str(geoid))

    def get_timeseries(self, geoid: str) -> dict | None:
        return self.timeseries.get(str(geoid))

    def boroughs(self) -> list[str]:
        vals = {t.get("borough") for t in self.tracts.values() if t.get("borough")}
        return sorted(vals)

    def districts(self) -> list[int]:
        vals = {
            int(t["council_district"]) for t in self.tracts.values()
            if t.get("council_district") is not None
        }
        return sorted(vals)

    def _compute_correlations(self) -> list[dict]:
        """Pearson r between each overlay column and risk_score (ported from
        app.correlation_with_risk), sorted by |r| descending."""
        cols = [
            cfg["col"] for label, cfg in OVERLAY_OPTIONS.items()
            if label != "Risk Score" and cfg["col"] in self.df.columns
        ]
        sub = self.df[cols + ["risk_score"]].apply(pd.to_numeric, errors="coerce").dropna()
        if sub.empty:
            return []
        corr = sub.corr(numeric_only=True)["risk_score"].drop("risk_score")
        corr = corr.dropna().sort_values(key=lambda s: s.abs(), ascending=False)
        return [
            {"column": col, "label": PRETTY.get(col, col), "r": float(r)}
            for col, r in corr.items()
        ]


# Module-level singleton, populated in the app lifespan.
store = DataStore()
