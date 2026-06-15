"""Test 2b — temporal split with a leave-one-out composite.

Same protocol as test_temporal_split, but the pre-cutoff composite is
rebuilt *without* `weighted_violation_rate`. That feature shares its
data source (HPD) with the post-cutoff outcome, so some of the signal
in test 2 could be autocorrelation of HPD volume over time rather than
genuine predictive validity.

If the reduced composite (closure_time + accountability_gap + vacate_rate)
still ranks tracts in a way that predicts future HPD volume, that's the
cleaner claim: the 311 / responsiveness signal alone foresees future
housing-code violations.

Interpretation:
  Spearman ρ ≥ 0.40  — strong predictive validity without HPD leakage
  Spearman ρ 0.25–0.40 — weaker but still real signal
  Spearman ρ < 0.25  — most of test 2's signal was HPD-on-HPD
                        autocorrelation; the non-HPD inputs alone aren't
                        predictive enough to stand on their own
"""
import sys

import pandas as pd
from scipy.stats import spearmanr

from pipeline.aggregate import aggregate
from pipeline.load_and_clean import (
    DATA_DIR, load_311, load_acs, load_tracts, load_vacate_orders,
)
from pipeline.regression import COMPOSITE_WEIGHTS
from pipeline.spatial_join import (
    join_311_to_tracts, join_hpd_to_tracts, join_vacate_to_tracts,
)
from validation.test_temporal_split import DEFAULT_CUTOFF, _load_hpd_with_dates
from validation.utils import print_header, silence_stdout, verdict

EXCLUDED = "weighted_violation_rate"


def _composite_without(tract_df: pd.DataFrame, excluded: str) -> pd.Series:
    """Percentile-rank composite over COMPOSITE_WEIGHTS minus `excluded`,
    renormalized so the remaining weights sum to 1. Returns a Series
    indexed like the rows of tract_df that had complete data."""
    weights = {f: w for f, w in COMPOSITE_WEIGHTS.items() if f != excluded}
    cols = [c for c in weights if c in tract_df.columns]
    df_valid = tract_df[cols].dropna()
    ranks = df_valid.rank(pct=True)
    weighted = sum(ranks[f] * weights[f] for f in cols)
    return (weighted / sum(weights[f] for f in cols)) * 100


def run(cutoff_date: str = DEFAULT_CUTOFF) -> dict:
    print_header(
        f"Test 2b — Temporal split, leave-one-out  "
        f"(cutoff: {cutoff_date}, excluded: {EXCLUDED})"
    )

    with silence_stdout():
        tracts = load_tracts()
        acs = load_acs()
        gdf_311 = load_311()
        gdf_vacate = load_vacate_orders()

    hpd_pre, hpd_post = _load_hpd_with_dates(
        DATA_DIR / "hpd_violations.csv", cutoff_date
    )
    print(f"HPD pre-cutoff rows:  {len(hpd_pre):,}")
    print(f"HPD post-cutoff rows: {len(hpd_post):,}")

    with silence_stdout():
        joined_311 = join_311_to_tracts(gdf_311, tracts)
        joined_hpd_pre = join_hpd_to_tracts(hpd_pre, tracts)
        joined_hpd_post = join_hpd_to_tracts(hpd_post, tracts)
        joined_vacate = join_vacate_to_tracts(gdf_vacate, tracts)
        tract_df = aggregate(
            tracts, joined_311, joined_hpd_pre, joined_vacate, acs
        )
        scores = _composite_without(tract_df, EXCLUDED)
        tract_df.loc[scores.index, "risk_score_loo"] = scores

    post_counts = (
        joined_hpd_post.groupby("GEOID").size()
        .rename("post_violations").reset_index()
    )

    result = (
        tract_df[["GEOID", "risk_score_loo", "housing_units"]]
        .merge(post_counts, on="GEOID", how="left")
        .assign(post_violations=lambda d: d["post_violations"].fillna(0))
    )
    result["post_rate"] = result["post_violations"] / result["housing_units"]
    result = result.dropna(subset=["risk_score_loo", "post_rate"])

    rho, p = spearmanr(result["risk_score_loo"], result["post_rate"])
    result["q"] = pd.qcut(
        result["risk_score_loo"], 5, labels=False, duplicates="drop"
    )
    quintile_rate = result.groupby("q")["post_rate"].mean()
    ratio = float(quintile_rate.iloc[-1] / (quintile_rate.iloc[0] + 1e-9))

    remaining = [f for f in COMPOSITE_WEIGHTS if f != EXCLUDED]
    print(f"\nComposite features used: {remaining}")
    print(f"N tracts: {len(result):,}")
    print(f"Spearman ρ (pre-risk → post-HPD-rate) = {rho:+.3f}  (p = {p:.2e})")
    print("Post-cutoff HPD-violation rate by pre-score quintile:")
    for q, v in quintile_rate.items():
        print(f"  Q{int(q)+1}: {v:.4f}")
    print(f"Top/bottom quintile ratio: {ratio:.2f}×")
    print(f"  {verdict(rho > 0.40)} strong validity without HPD leakage (ρ > 0.40)")
    print(f"  {verdict(rho > 0.25)} residual signal exists (ρ > 0.25)")
    print(f"  {verdict(ratio > 2.0)} quintile separation (> 2×)")

    return {
        "spearman_rho": float(rho),
        "spearman_p": float(p),
        "top_bottom_ratio": ratio,
        "n_tracts": int(len(result)),
        "cutoff": cutoff_date,
        "excluded_feature": EXCLUDED,
    }


if __name__ == "__main__":
    cutoff = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CUTOFF
    run(cutoff)
