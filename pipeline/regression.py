import pandas as pd

# Hand-chosen weights based on conceptual importance, not regression fit.
# Justification: accountability_gap is the most directly interpretable signal of
# institutional neglect (violations exist but no one's complaining). Severity-weighted
# violation rate captures actual housing danger. Closure time captures responsiveness.
# Vacate rate is included with low weight because it's already baked into weighted_violation_rate.
#
# Closure-time entry is `avg_closure_time_adjusted`, not the raw `avg_closure_time`.
# The adjusted column has been double-corrected in aggregate.py:
#   1. Each record divided by the citywide median for its complaint type
#      (removes complaint-type variance — heat vs. mold etc.)
#   2. Tract-level mean residualized against violation_rate via OLS
#      (removes HPD triage endogeneity — high-violation tracts get faster response)
COMPOSITE_WEIGHTS = {
    "accountability_gap": 0.40,
    "weighted_violation_rate": 0.30,
    "avg_closure_time_adjusted": 0.20,
    "vacate_rate": 0.10,
}


def run_rank_composite(tract_df: pd.DataFrame):
    df = tract_df.copy()
    feature_cols = [c for c in COMPOSITE_WEIGHTS if c in df.columns]
    df_valid = df[feature_cols].dropna()

    print("\n=== Correlation Matrix ===")
    print(df_valid.corr().round(3))

    print("\n=== Composite Weights ===")
    for f, w in COMPOSITE_WEIGHTS.items():
        if f in feature_cols:
            print(f"  {f}: {w:.0%}")

    # Convert each feature to its percentile rank (0–1)
    ranks = df_valid.rank(pct=True)

    # Weighted sum
    weighted = sum(ranks[f] * COMPOSITE_WEIGHTS[f] for f in feature_cols)
    weight_total = sum(COMPOSITE_WEIGHTS[f] for f in feature_cols)
    composite = (weighted / weight_total) * 100  # scale to 0–100

    print("\n=== Composite Score Distribution ===")
    print(composite.describe().round(2))

    return composite, feature_cols


if __name__ == "__main__":
    from pipeline.load_and_clean import (
        load_tracts, load_311, load_hpd, load_vacate_orders, load_acs,
    )
    from pipeline.spatial_join import (
        join_311_to_tracts, join_hpd_to_tracts, join_vacate_to_tracts,
    )
    from pipeline.aggregate import aggregate

    tracts = load_tracts()
    gdf_311 = load_311()
    gdf_hpd = load_hpd()
    gdf_vacate = load_vacate_orders()
    acs = load_acs()
    joined_311 = join_311_to_tracts(gdf_311, tracts)
    joined_hpd = join_hpd_to_tracts(gdf_hpd, tracts)
    joined_vacate = join_vacate_to_tracts(gdf_vacate, tracts)
    tract_df = aggregate(tracts, joined_311, joined_hpd, joined_vacate, acs)

    scores, feature_cols = run_rank_composite(tract_df)
    print(scores.head())
