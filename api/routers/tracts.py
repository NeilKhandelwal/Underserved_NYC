from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from .. import service
from ..deps import get_store
from ..schemas import TractDetail, TractSummary, TractTimeSeries
from ..store import DataStore

router = APIRouter(tags=["tracts"])


@router.get("/tracts", response_model=list[TractSummary])
def list_tracts(store: DataStore = Depends(get_store)):
    """Lightweight list of every tract (id, name, score, residual)."""
    return [
        {
            "geoid": str(t.get("GEOID")),
            "neighborhood": t.get("neighborhood"),
            "borough": t.get("borough"),
            "council_district": t.get("council_district"),
            "risk_score": t.get("risk_score"),
            "risk_residual": t.get("risk_residual"),
        }
        for t in store.tracts.values()
    ]


@router.get("/districts", response_model=list[int])
def list_districts(store: DataStore = Depends(get_store)):
    """Sorted distinct City Council district numbers present in the data."""
    return store.districts()


@router.get("/tract/{geoid}", response_model=TractDetail)
def get_tract(geoid: str, store: DataStore = Depends(get_store)):
    """Full detail for one tract: score, residual, and metric-vs-city comparisons."""
    detail = service.tract_detail(store, geoid)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"Unknown GEOID: {geoid}")
    return detail


@router.get("/tract/{geoid}/timeseries", response_model=TractTimeSeries)
def get_tract_timeseries(geoid: str, store: DataStore = Depends(get_store)):
    """Quarterly risk-score series for one tract (powers the trend sparkline).

    404s when the tract has no series — either an unknown GEOID or a bundle built
    without the optional ``timeseries.json`` (run `make timeseries`)."""
    series = store.get_timeseries(geoid)
    if series is None:
        raise HTTPException(
            status_code=404, detail=f"No time series for GEOID: {geoid}"
        )
    return {"geoid": str(geoid), **series}
