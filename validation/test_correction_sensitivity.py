"""Test 6 — sensitivity to the bias corrections (steps 1c and 1d).

The pipeline applies two OLS residualizations before the rank composite:
  1c. complaint_rate residualized against log(median_income)
       → complaint_rate_adjusted (used in accountability_gap)
  1d. avg_closure_ratio residualized against violation_rate
       → avg_closure_time_adjusted (used directly in the composite)

Both are *opinionated* — they assume violation_rate / log(income) are
confounders to be removed, not mediators on the same causal pathway.
This test asks: how much does the index actually depend on those
assumptions?

Recomputes the composite with each correction (and both) disabled, then
reports rank-correlation, top-N overlap, and the biggest movers vs. the
production index. If the top-20 barely changes, the corrections are
inert. If it reshuffles a lot, the corrections are doing real work.

Reads output/master.geojson — both raw (`complaint_rate`,
`avg_closure_ratio`) and adjusted columns are present.
"""
import pandas as pd
from scipy.stats import kendalltau, spearmanr

from pipeline.regression import COMPOSITE_WEIGHTS
from validation.utils import load_master_geojson, print_header, verdict


def _composite_with(df: pd.DataFrame, gap_col: str, closure_col: str) -> pd.Series:
    """Rank composite with arbitrary swap-ins for the gap and closure inputs.
    Returns a GEOID-indexed Series of 0–100 scores."""
    cols_used = [gap_col, "weighted_violation_rate", closure_col, "vacate_rate"]
    sub = df[["GEOID"] + cols_used].dropna()
    ranks = sub[cols_used].rank(pct=True)
    w = COMPOSITE_WEIGHTS
    weighted = (
        ranks[gap_col] * w["accountability_gap"]
        + ranks["weighted_violation_rate"] * w["weighted_violation_rate"]
        + ranks[closure_col] * w["avg_closure_time_adjusted"]
        + ranks["vacate_rate"] * w["vacate_rate"]
    )
    composite = (weighted / sum(w.values())) * 100
    composite.index = sub["GEOID"].values
    return composite


def _comparison(base: pd.Series, alt: pd.Series, top_ns=(20, 50, 100)) -> dict:
    common = base.index.intersection(alt.index)
    b = base.loc[common]
    a = alt.loc[common]
    rho, _ = spearmanr(b, a)
    tau, _ = kendalltau(b, a)
    # Higher score = more underserved → ascending=False so rank 1 is worst tract
    b_rank = b.rank(ascending=False)
    a_rank = a.rank(ascending=False)
    delta = (b_rank - a_rank).abs()
    overlaps = {}
    for n in top_ns:
        bt = set(b.nlargest(n).index)
        at = set(a.nlargest(n).index)
        overlaps[f"top_{n}_overlap"] = len(bt & at) / n
    return {
        "spearman_rho": float(rho),
        "kendall_tau": float(tau),
        "mean_abs_rank_change": float(delta.mean()),
        "median_abs_rank_change": float(delta.median()),
        "max_abs_rank_change": int(delta.max()),
        **overlaps,
    }


def run() -> dict:
    print_header("Test 6 — Bias-correction sensitivity (steps 1c + 1d)")

    gdf = load_master_geojson()
    df = pd.DataFrame(gdf.drop(columns="geometry"))

    required = {
        "complaint_rate", "complaint_rate_adjusted",
        "avg_closure_ratio", "avg_closure_time_adjusted",
        "weighted_violation_rate", "vacate_rate", "accountability_gap",
    }
    missing = required - set(df.columns)
    if missing:
        raise RuntimeError(
            f"master.geojson missing columns needed for this test: {missing}. "
            "Re-run `python -m pipeline.score`."
        )

    # Reconstruct accountability_gap from RAW complaint_rate so we can
    # toggle step 1c off. (The version stored in master.geojson uses the
    # adjusted complaint rate.)
    df["accountability_gap_raw"] = (
        df["weighted_violation_rate"] / (df["complaint_rate"] + 0.001)
    )

    base = _composite_with(df, "accountability_gap", "avg_closure_time_adjusted")

    variants = {
        "no_income_correction (1c off)":
            _composite_with(df, "accountability_gap_raw", "avg_closure_time_adjusted"),
        "no_triage_correction (1d off)":
            _composite_with(df, "accountability_gap", "avg_closure_ratio"),
        "no_corrections (both off)":
            _composite_with(df, "accountability_gap_raw", "avg_closure_ratio"),
    }

    print(f"\nN tracts compared: {len(base):,}")
    print(f"Production composite range: [{base.min():.1f}, {base.max():.1f}]")

    results = {}
    for name, alt in variants.items():
        stats = _comparison(base, alt)
        results[name] = stats
        print(f"\n=== {name}  vs  production ===")
        print(f"  Spearman ρ:           {stats['spearman_rho']:+.3f}")
        print(f"  Kendall τ:            {stats['kendall_tau']:+.3f}")
        print(f"  Top-20 overlap:       {stats['top_20_overlap']:.0%}")
        print(f"  Top-50 overlap:       {stats['top_50_overlap']:.0%}")
        print(f"  Top-100 overlap:      {stats['top_100_overlap']:.0%}")
        print(f"  Median |Δrank|:       {stats['median_abs_rank_change']:.0f}")
        print(f"  Mean   |Δrank|:       {stats['mean_abs_rank_change']:.1f}")
        print(f"  Max    |Δrank|:       {stats['max_abs_rank_change']}")

    # For the both-off variant, list the tracts most affected by the corrections
    raw = variants["no_corrections (both off)"]
    common = base.index.intersection(raw.index)
    b_rank = base.loc[common].rank(ascending=False)
    r_rank = raw.loc[common].rank(ascending=False)
    delta = (b_rank - r_rank).rename("delta_rank")  # positive = production ranks worse

    geoid_to_neighborhood = (
        df[["GEOID", "neighborhood", "borough"]].drop_duplicates("GEOID")
        .set_index("GEOID")
    )
    movers = pd.DataFrame({
        "production_rank": b_rank.astype(int),
        "raw_rank": r_rank.astype(int),
        "delta": delta.astype(int),
        "production_score": base.loc[common].round(1),
        "raw_score": raw.loc[common].round(1),
    })
    movers = movers.join(geoid_to_neighborhood)

    print("\n=== Top 10 tracts the CORRECTIONS LIFT (worse in production than raw) ===")
    print("    (these are tracts the bias adjustments flag as more underserved)")
    print(movers.nsmallest(10, "delta")[
        ["neighborhood", "borough", "raw_rank", "production_rank",
         "raw_score", "production_score"]
    ].to_string())

    print("\n=== Top 10 tracts the CORRECTIONS SUPPRESS (better in production than raw) ===")
    print("    (these are tracts the bias adjustments flag as less underserved)")
    print(movers.nlargest(10, "delta")[
        ["neighborhood", "borough", "raw_rank", "production_rank",
         "raw_score", "production_score"]
    ].to_string())

    # Headline verdicts: did the corrections do meaningful work?
    both_off = results["no_corrections (both off)"]
    print("\n=== Headline verdicts ===")
    print(
        f"  {verdict(both_off['top_20_overlap'] >= 0.80)} "
        f"top-20 stable to ≥80% (corrections aren't reshuffling the worst tracts)"
    )
    print(
        f"  {verdict(both_off['spearman_rho'] >= 0.95)} "
        f"overall ranking ρ ≥ 0.95 (corrections nudge order, don't rewrite it)"
    )
    print(
        f"  {verdict(both_off['mean_abs_rank_change'] < 50)} "
        f"mean rank shift < 50 places (typical tract barely moves)"
    )

    return results


if __name__ == "__main__":
    run()
