from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query

from .. import service
from ..deps import get_store
from ..schemas import WatchlistGroupRow, WatchlistRow
from ..store import DataStore

router = APIRouter(tags=["watchlist"])


@router.get("/watchlist", response_model=list[WatchlistRow])
def get_watchlist(
    direction: Literal["neglect", "success", "surprise"] = "neglect",
    borough: list[str] | None = Query(default=None),
    district: list[int] | None = Query(default=None),
    n: int = Query(default=20, ge=1, le=100),
    store: DataStore = Depends(get_store),
):
    """Top residual outliers.

    - **neglect**: most unexplained neglect (residual ↑)
    - **success**: unexpected success (residual ↓)
    - **surprise**: biggest absolute surprises (|residual|)
    """
    return service.watchlist(
        store, direction=direction, boroughs=borough, districts=district, n=n,
    )


@router.get("/watchlist/groups", response_model=list[WatchlistGroupRow])
def get_watchlist_groups(
    by: Literal["neighborhood", "council_district"] = "neighborhood",
    direction: Literal["neglect", "success", "surprise"] = "neglect",
    borough: list[str] | None = Query(default=None),
    n: int = Query(default=20, ge=1, le=100),
    min_tracts: int = Query(default=2, ge=1),
    store: DataStore = Depends(get_store),
):
    """Watchlist aggregated by neighborhood or council district — mean residual
    over *all* matching tracts, with each area's most extreme tract."""
    return service.watchlist_groups(
        store, by=by, direction=direction, boroughs=borough, n=n, min_tracts=min_tracts,
    )
