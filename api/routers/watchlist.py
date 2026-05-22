from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query

from .. import service
from ..deps import get_store
from ..schemas import WatchlistRow
from ..store import DataStore

router = APIRouter(tags=["watchlist"])


@router.get("/watchlist", response_model=list[WatchlistRow])
def get_watchlist(
    direction: Literal["neglect", "success", "surprise"] = "neglect",
    borough: list[str] | None = Query(default=None),
    n: int = Query(default=20, ge=1, le=100),
    store: DataStore = Depends(get_store),
):
    """Top residual outliers.

    - **neglect**: most unexplained neglect (residual ↑)
    - **success**: unexpected success (residual ↓)
    - **surprise**: biggest absolute surprises (|residual|)
    """
    return service.watchlist(store, direction=direction, boroughs=borough, n=n)
