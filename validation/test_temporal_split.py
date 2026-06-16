"""Test 2 — predictive validity via temporal split.

Rebuild the risk score using only HPD violations dated *before* a cutoff
(the training window). Then count how many HPD violations each tract
accumulated *after* the cutoff. If the pre-cutoff risk score really
identifies neglect, post-cutoff violation rates should rank correlate
with it. 311 and vacate inputs are held constant — this is a deliberate
simplification (documented below) to avoid re-parsing every source.

Interpretation:
  Spearman ρ ≥ 0.30  — meaningful predictive signal
  Top/bottom-quintile ratio ≥ 2× — top-risk tracts see 2× the HPD
                                     violations of bottom-risk tracts
"""
import sys

import pandas as pd
from scipy.stats import spearmanr

from pipeline.load_and_clean import (
    load_311, load_acs, load_hpd_with_dates, load_tracts, load_vacate_orders,
)
from pipeline.aggregate import aggregate
from pipeline.regression import run_rank_composite
from pipeline.spatial_join import (
    join_311_to_tracts, join_hpd_to_tracts, join_vacate_to_tracts,
)
from validation.utils import print_header, silence_stdout, verdict

DEFAULT_CUTOFF = "2024-10-01"  # leaves ~6 months of "future" data


def run(cutoff_date: str = DEFAULT_CUTOFF) -> dict:
    print_header(f"Test 2 — Temporal split  (cutoff: {cutoff_date})")

    with silence_stdout():
        tracts = load_tracts()
        acs = load_acs()
        gdf_311 = load_311()
        gdf_vacate = load_vacate_orders()

    hpd_pre, hpd_post = load_hpd_with_dates(cutoff_date)
    print(f"HPD pre-cutoff rows:  {len(hpd_pre):,}")
    print(f"HPD post-cutoff rows: {len(hpd_post):,}")
    if len(hpd_post) < 5000:
        print(
            "  [WARN] Fewer than 5k post-cutoff violations — temporal window may "
            "be too short for a reliable validation. Try an earlier cutoff."
        )

    with silence_stdout():
        joined_311 = join_311_to_tracts(gdf_311, tracts)
        joined_hpd_pre = join_hpd_to_tracts(hpd_pre, tracts)
        joined_hpd_post = join_hpd_to_tracts(hpd_post, tracts)
        joined_vacate = join_vacate_to_tracts(gdf_vacate, tracts)
        tract_df = aggregate(
            tracts, joined_311, joined_hpd_pre, joined_vacate, acs
        )
        scores, _ = run_rank_composite(tract_df)
        tract_df.loc[scores.index, "risk_score"] = scores

    post_counts = (
        joined_hpd_post.groupby("GEOID").size().rename("post_violations").reset_index()
    )

    result = (
        tract_df[["GEOID", "risk_score", "housing_units"]]
        .merge(post_counts, on="GEOID", how="left")
        .assign(post_violations=lambda d: d["post_violations"].fillna(0))
    )
    result["post_rate"] = result["post_violations"] / result["housing_units"]
    result = result.dropna(subset=["risk_score", "post_rate"])

    rho, p = spearmanr(result["risk_score"], result["post_rate"])
    result["q"] = pd.qcut(result["risk_score"], 5, labels=False, duplicates="drop")
    quintile_rate = result.groupby("q")["post_rate"].mean()
    ratio = float(quintile_rate.iloc[-1] / (quintile_rate.iloc[0] + 1e-9))

    print(f"\nN tracts: {len(result):,}")
    print(f"Spearman ρ (pre-risk → post-HPD-rate) = {rho:+.3f}  (p = {p:.2e})")
    print("Post-cutoff HPD-violation rate by pre-score quintile:")
    for q, v in quintile_rate.items():
        print(f"  Q{int(q)+1}: {v:.4f}")
    print(f"Top/bottom quintile ratio: {ratio:.2f}×")
    print(f"  {verdict(rho > 0.30)} predictive validity (ρ > 0.30)")
    print(f"  {verdict(ratio > 2.0)} quintile separation (> 2×)")

    return {
        "spearman_rho": float(rho),
        "spearman_p": float(p),
        "top_bottom_ratio": ratio,
        "n_tracts": int(len(result)),
        "cutoff": cutoff_date,
    }


if __name__ == "__main__":
    cutoff = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CUTOFF
    run(cutoff)
