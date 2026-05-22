from __future__ import annotations

from fastapi import APIRouter, Depends

from .. import service
from ..deps import get_store
from ..schemas import PredictRequest, PredictResponse
from ..store import DataStore

router = APIRouter(tags=["predict"])


@router.post("/predict", response_model=PredictResponse)
def predict(req: PredictRequest, store: DataStore = Depends(get_store)):
    """Predict a risk score from demographic inputs via the trained RF.

    Send any subset of features; omitted ones default to the training median,
    out-of-range values are clamped to the training range.
    """
    return service.predict_risk(store, req.inputs)
