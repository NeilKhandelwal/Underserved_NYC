from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from .. import service
from ..deps import get_store
from ..schemas import TractDetail, TractSummary
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
            "risk_score": t.get("risk_score"),
            "risk_residual": t.get("risk_residual"),
        }
        for t in store.tracts.values()
    ]


@router.get("/tract/{geoid}", response_model=TractDetail)
def get_tract(geoid: str, store: DataStore = Depends(get_store)):
    """Full detail for one tract: score, residual, and metric-vs-city comparisons."""
    detail = service.tract_detail(store, geoid)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"Unknown GEOID: {geoid}")
    return detail
