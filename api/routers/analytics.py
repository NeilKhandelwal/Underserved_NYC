from __future__ import annotations

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException

from ..deps import get_store
from ..overlays import PRETTY, overlay_list, residual_bins
from ..schemas import Correlation, ModelInfo, OverlaysResponse, ScatterResponse
from ..store import DataStore

router = APIRouter(tags=["analytics"])


@router.get("/correlations", response_model=list[Correlation])
def get_correlations(store: DataStore = Depends(get_store)):
    """Pearson r between each demographic and the risk score, sorted by |r|."""
    return store.correlations


@router.get("/scatter/{column}", response_model=ScatterResponse)
def get_scatter(column: str, store: DataStore = Depends(get_store)):
    """Per-tract (feature value, risk_score) pairs for one correlation column,
    so the Demographics tab can draw the underlying scatterplot."""
    match = next((c for c in store.correlations if c["column"] == column), None)
    if match is None:
        raise HTTPException(404, f"no correlation column named {column!r}")
    sub = store.df[[column, "risk_score"]].apply(pd.to_numeric, errors="coerce").dropna()
    points = [[float(x), float(y)] for x, y in sub.itertuples(index=False)]
    return {
        "column": column,
        "label": PRETTY.get(column, column),
        "r": match["r"],
        "n": len(points),
        "points": points,
    }


@router.get("/model", response_model=ModelInfo)
def get_model(store: DataStore = Depends(get_store)):
    """RF metadata: features, held-out R²/RMSE, importances, slider ranges."""
    meta = store.model_meta
    return {
        "features": meta["features"],
        "labels": {f: PRETTY.get(f, f) for f in meta["features"]},
        "r2": meta["r2"],
        "rmse": meta["rmse"],
        "importance": meta["importance"],
        "feature_ranges": meta["feature_ranges"],
    }


@router.get("/overlays", response_model=OverlaysResponse)
def get_overlays(store: DataStore = Depends(get_store)):
    """Map overlay definitions (with color domains) + the fixed symmetric bins
    for the residual layer."""
    overlays = overlay_list()
    for o in overlays:
        stat = store.citywide.get(o["column"])
        o["domain"] = [stat["min"], stat["max"]] if stat else None
    residuals = [t.get("risk_residual") for t in store.tracts.values()]
    return {"overlays": overlays, "residual_bins": residual_bins(residuals)}
