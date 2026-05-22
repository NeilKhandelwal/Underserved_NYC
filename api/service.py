"""Pure business logic, ported from app.py. Kept free of FastAPI types so it
stays unit-testable in isolation."""
from __future__ import annotations

from .store import DataStore

# (column, label, unit) for the detail panel — mirrors sidebar_panel() in app.py.
METRIC_ROWS = [
    ("avg_closure_time", "Avg 311 Closure Time", " days"),
    ("accountability_gap", "Accountability Gap", ""),
    ("weighted_violation_rate", "Severity-Weighted Violation Rate", ""),
    ("vacate_rate", "Vacate Order Rate", ""),
    ("median_income", "Median Household Income", ""),
]

# Watchlist sort directions.
DIRECTIONS = {"neglect", "success", "surprise"}


def band(score: float | None) -> str:
    """Risk band thresholds from app.py (>=75 red, >=50 amber, else teal)."""
    if score is None:
        return "low"
    if score >= 75:
        return "high"
    if score >= 50:
        return "elevated"
    return "low"


def tract_detail(store: DataStore, geoid: str) -> dict | None:
    props = store.get_tract(geoid)
    if props is None:
        return None

    score = props.get("risk_score")
    metrics = []
    for col, label, unit in METRIC_ROWS:
        value = props.get(col)
        citywide_mean = (store.citywide.get(col) or {}).get("mean")
        ratio = direction = None
        if value is not None and citywide_mean not in (None, 0):
            ratio = value / citywide_mean
            direction = "higher" if ratio > 1 else "lower"
        metrics.append({
            "key": col,
            "label": label,
            "value": value,
            "citywide_mean": citywide_mean,
            "ratio": ratio,
            "direction": direction,
            "unit": unit,
        })

    return {
        "geoid": str(props.get("GEOID")),
        "neighborhood": props.get("neighborhood"),
        "borough": props.get("borough"),
        "risk_score": score,
        "predicted_risk": props.get("predicted_risk"),
        "risk_residual": props.get("risk_residual"),
        "band": band(score),
        "metrics": metrics,
        "properties": props,
    }


def watchlist(
    store: DataStore,
    direction: str = "neglect",
    boroughs: list[str] | None = None,
    n: int = 20,
) -> list[dict]:
    """Top residual outliers, ported from the Watchlist tab in app.py."""
    rows = [
        t for t in store.tracts.values()
        if t.get("risk_residual") is not None
        and (not boroughs or t.get("borough") in boroughs)
    ]
    if direction == "neglect":          # most unexplained neglect (+)
        rows.sort(key=lambda t: t["risk_residual"], reverse=True)
    elif direction == "success":        # unexpected success (−)
        rows.sort(key=lambda t: t["risk_residual"])
    else:                               # biggest surprises (|residual|)
        rows.sort(key=lambda t: abs(t["risk_residual"]), reverse=True)

    return [
        {
            "geoid": str(t.get("GEOID")),
            "neighborhood": t.get("neighborhood"),
            "borough": t.get("borough"),
            "risk_score": t.get("risk_score"),
            "risk_residual": t.get("risk_residual"),
        }
        for t in rows[:n]
    ]


def predict_risk(store: DataStore, raw_inputs: dict[str, float]) -> dict:
    """RF prediction from demographics. Missing features default to the training
    median; out-of-range inputs are clamped (mirrors the app's slider bounds)."""
    features = store.model_meta["features"]
    ranges = store.model_meta["feature_ranges"]

    used: dict[str, float] = {}
    clamped: list[str] = []
    for f in features:
        r = ranges[f]
        lo, hi = float(r["min"]), float(r["max"])
        if f in raw_inputs and raw_inputs[f] is not None:
            v = float(raw_inputs[f])
            if v < lo:
                v, _ = lo, clamped.append(f)
            elif v > hi:
                v, _ = hi, clamped.append(f)
        else:
            v = float(r["median"])
        used[f] = v

    # Plain 2-D array matches how the model was trained (no feature names),
    # so this stays in lockstep with pipeline.demographic_analysis.
    X = [[used[f] for f in features]]
    pred = float(store.model.predict(X)[0])
    return {
        "predicted_risk": pred,
        "band": band(pred),
        "inputs_used": used,
        "clamped": clamped,
    }
