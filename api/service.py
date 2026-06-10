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

# Watchlist grouping levels: per-tract property -> display key formatter.
GROUP_LEVELS = {
    "neighborhood": lambda v: str(v),
    "council_district": lambda v: f"District {int(v)}",
}

# The 4 risk-score components, in composite-weight order (see Methodology).
COMPONENT_KEYS = (
    "accountability_gap",
    "weighted_violation_rate",
    "avg_closure_time",
    "vacate_rate",
)
COMPONENT_LABELS = {
    "accountability_gap": "accountability gap",
    "weighted_violation_rate": "severity-weighted violation rate",
    "avg_closure_time": "311 closure time",
    "vacate_rate": "vacate order rate",
}


def band(score: float | None) -> str:
    """Risk band thresholds from app.py (>=75 red, >=50 amber, else teal)."""
    if score is None:
        return "low"
    if score >= 75:
        return "high"
    if score >= 50:
        return "elevated"
    return "low"


def interpretation(props: dict, metrics: list[dict]) -> str | None:
    """One-line plain-language readout: how far the tract sits from its
    demographic prediction, and which risk component drives it most."""
    residual = props.get("risk_residual")
    if residual is None:
        return None
    line = f"Scores {residual:+.0f} points vs. demographic prediction"
    if abs(residual) < 10:  # inside the model's RMSE noise floor
        return line + " (within the model's noise floor)"

    ratios = {
        m["key"]: m["ratio"] for m in metrics
        if m["key"] in COMPONENT_KEYS and m["ratio"] is not None
    }
    if ratios:
        if residual > 0:
            key = max(ratios, key=ratios.get)
            if ratios[key] > 1:
                line += f"; main driver: {COMPONENT_LABELS[key]} {ratios[key]:.1f}× city average"
        else:
            key = min(ratios, key=ratios.get)
            if ratios[key] < 1:
                line += f"; best metric: {COMPONENT_LABELS[key]} {ratios[key]:.1f}× city average"
    return line


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
        "council_district": props.get("council_district"),
        "risk_score": score,
        "predicted_risk": props.get("predicted_risk"),
        "risk_residual": props.get("risk_residual"),
        "band": band(score),
        "interpretation": interpretation(props, metrics),
        "metrics": metrics,
        "properties": props,
    }


def _sort_rows(rows: list, key, direction: str) -> None:
    if direction == "neglect":          # most unexplained neglect (+)
        rows.sort(key=key, reverse=True)
    elif direction == "success":        # unexpected success (−)
        rows.sort(key=key)
    else:                               # biggest surprises (|residual|)
        rows.sort(key=lambda r: abs(key(r)), reverse=True)


def watchlist(
    store: DataStore,
    direction: str = "neglect",
    boroughs: list[str] | None = None,
    districts: list[int] | None = None,
    n: int = 20,
) -> list[dict]:
    """Top residual outliers, ported from the Watchlist tab in app.py."""
    rows = [
        t for t in store.tracts.values()
        if t.get("risk_residual") is not None
        and (not boroughs or t.get("borough") in boroughs)
        and (not districts or t.get("council_district") in districts)
    ]
    _sort_rows(rows, lambda t: t["risk_residual"], direction)

    return [
        {
            "geoid": str(t.get("GEOID")),
            "neighborhood": t.get("neighborhood"),
            "borough": t.get("borough"),
            "council_district": t.get("council_district"),
            "risk_score": t.get("risk_score"),
            "predicted_risk": t.get("predicted_risk"),
            "risk_residual": t.get("risk_residual"),
            "median_income": t.get("median_income"),
        }
        for t in rows[:n]
    ]


def watchlist_groups(
    store: DataStore,
    by: str = "neighborhood",
    direction: str = "neglect",
    boroughs: list[str] | None = None,
    n: int = 20,
    min_tracts: int = 2,
) -> list[dict]:
    """Watchlist aggregated by neighborhood or council district, so the list
    reads as 'areas needing attention' rather than individual tracts."""
    fmt = GROUP_LEVELS[by]
    groups: dict[str, list[dict]] = {}
    for t in store.tracts.values():
        if t.get("risk_residual") is None or t.get(by) is None:
            continue
        if boroughs and t.get("borough") not in boroughs:
            continue
        groups.setdefault(fmt(t[by]), []).append(t)

    extreme = max if direction != "success" else min
    rows = []
    for key, tracts in groups.items():
        if len(tracts) < min_tracts:
            continue
        residuals = [t["risk_residual"] for t in tracts]
        risks = [t["risk_score"] for t in tracts if t.get("risk_score") is not None]
        if direction == "surprise":
            top = max(tracts, key=lambda t: abs(t["risk_residual"]))
        else:
            top = extreme(tracts, key=lambda t: t["risk_residual"])
        rows.append({
            "key": key,
            "group_by": by,
            "borough": " / ".join(sorted({t["borough"] for t in tracts if t.get("borough")})) or None,
            "tract_count": len(tracts),
            "mean_residual": sum(residuals) / len(residuals),
            "mean_risk": sum(risks) / len(risks) if risks else None,
            "top_geoid": str(top.get("GEOID")),
            "top_neighborhood": top.get("neighborhood"),
            "top_residual": top["risk_residual"],
        })

    _sort_rows(rows, lambda r: r["mean_residual"], direction)
    return rows[:n]


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
