"""Map-overlay definitions and color logic, ported from app.py.

The frontend (MapLibre) consumes /api/overlays to build the layer switcher
and data-driven fill styling, so the visual semantics live here once.
"""
from __future__ import annotations

import math

# Mirrors OVERLAY_OPTIONS in app.py.
OVERLAY_OPTIONS: dict[str, dict] = {
    "Risk Score": {"col": "risk_score", "fmt": "{:.1f}", "legend": "Underservice Risk Score (0–100)"},
    "Unexplained Neglect (Residual)": {
        "col": "risk_residual", "fmt": "{:+.1f}",
        "legend": "Risk Score − RF Prediction (red = more neglect than demographics predict)",
    },
    "Predicted Risk (from demographics)": {
        "col": "predicted_risk", "fmt": "{:.1f}",
        "legend": "Random Forest Prediction (0–100)",
    },
    "Median Income": {"col": "median_income", "fmt": "${:,.0f}", "legend": "Median Household Income ($)"},
    "Poverty Rate": {"col": "poverty_rate", "fmt": "{:.1%}", "legend": "Poverty Rate"},
    "% Black": {"col": "pct_black", "fmt": "{:.1%}", "legend": "% Black / African American"},
    "% Hispanic": {"col": "pct_hispanic", "fmt": "{:.1%}", "legend": "% Hispanic or Latino"},
    "% Foreign-Born": {"col": "pct_foreign_born", "fmt": "{:.1%}", "legend": "% Foreign-Born"},
    "Rent Burden": {"col": "rent_burden", "fmt": "{:.1%}", "legend": "% Renters Paying ≥50% Income on Rent"},
    "Unemployment": {"col": "unemployment_rate", "fmt": "{:.1%}", "legend": "Unemployment Rate"},
    "% Bachelor's+": {"col": "pct_bachelors", "fmt": "{:.1%}", "legend": "% with Bachelor's Degree or Higher"},
}

# Protective demographics: higher = less concerning, so the scale is inverted.
INVERTED = {"Median Income", "% Bachelor's+"}

# Display labels keyed by column (for predictor / correlations / model panels).
PRETTY: dict[str, str] = {cfg["col"]: label for label, cfg in OVERLAY_OPTIONS.items()}
PRETTY.setdefault("mean_commute_time", "Aggregate Commute Time")
PRETTY.setdefault("median_year_built", "Median Year Built")
PRETTY.setdefault("pct_prewar_units", "% Pre-War Units")
PRETTY.setdefault("pct_rent_stab_proxy", "% Rent-Stabilized (proxy)")


def overlay_list() -> list[dict]:
    out = []
    for label, cfg in OVERLAY_OPTIONS.items():
        reverse = label in INVERTED
        out.append({
            "label": label,
            "column": cfg["col"],
            "format": cfg["fmt"],
            "legend": cfg["legend"],
            "scheme": "RdYlGn" if reverse else "RdYlGn_r",
            "reverse": reverse,
            "symmetric_bins": cfg["col"] == "risk_residual",
        })
    return out


def residual_bins(values) -> list[float] | None:
    """Fixed symmetric bins for the residual layer (ported from make_map):
    inside ±10 sits in the RMSE noise floor; |residual| > 20 reads as an outlier.
    """
    vals = [abs(float(v)) for v in values if v is not None]
    if not vals:
        return None
    abs_max = max(vals)
    edge = max(25.0, math.ceil(abs_max / 5.0) * 5.0)
    return [-edge, -20.0, -10.0, 0.0, 10.0, 20.0, edge]
