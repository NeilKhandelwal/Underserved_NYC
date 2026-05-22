from __future__ import annotations

from pydantic import BaseModel, Field


class MetricComparison(BaseModel):
    key: str
    label: str
    value: float | None
    citywide_mean: float | None
    ratio: float | None = None
    direction: str | None = None  # "higher" | "lower"
    unit: str = ""


class TractSummary(BaseModel):
    geoid: str
    neighborhood: str | None
    borough: str | None
    risk_score: float | None
    risk_residual: float | None = None


class TractDetail(TractSummary):
    predicted_risk: float | None = None
    band: str  # "high" | "elevated" | "low"
    metrics: list[MetricComparison]
    properties: dict  # full per-tract record (public-API escape hatch)


class WatchlistRow(TractSummary):
    pass


class Correlation(BaseModel):
    column: str
    label: str
    r: float


class FeatureRange(BaseModel):
    min: float
    max: float
    median: float


class ModelInfo(BaseModel):
    features: list[str]
    labels: dict[str, str]
    r2: float
    rmse: float
    importance: dict[str, float]
    feature_ranges: dict[str, FeatureRange]


class OverlayInfo(BaseModel):
    label: str
    column: str
    format: str
    legend: str
    scheme: str
    reverse: bool
    symmetric_bins: bool


class OverlaysResponse(BaseModel):
    overlays: list[OverlayInfo]
    residual_bins: list[float] | None


class PredictRequest(BaseModel):
    inputs: dict[str, float] = Field(
        default_factory=dict,
        description="feature -> value. Missing features default to the training "
                    "median; out-of-range values are clamped to the training range.",
    )


class PredictResponse(BaseModel):
    predicted_risk: float
    band: str
    inputs_used: dict[str, float]
    clamped: list[str]


class HealthResponse(BaseModel):
    status: str
    tracts: int
    model_loaded: bool
