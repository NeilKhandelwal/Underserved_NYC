"""Test 3 — bootstrap per-tract confidence intervals.

Resample (with replacement) the joined 311, HPD, and vacate records and
re-run the full composite pipeline B times. For each tract we get a
distribution of risk scores, and from that a 90% CI. Wide CIs mean the
point estimate is unreliable for that tract; tight CIs mean it's a
defensible claim.

Writes per-tract CIs to output/validation_bootstrap_ci.csv for inspection.

Runtime: ~2s per iteration × B. Default B=200 (~7 min). Bump to 500 for
publication-quality CIs; drop to 50 for a quick smoke test.
"""
import sys

import numpy as np
import pandas as pd

from pipeline.aggregate import aggregate
from pipeline.load_and_clean import (
    DATA_DIR, load_311, load_acs, load_hpd, load_tracts, load_vacate_orders,
)
from pipeline.regression import run_rank_composite
from pipeline.spatial_join import (
    join_311_to_tracts, join_hpd_to_tracts, join_vacate_to_tracts,
)
from validation.utils import OUTPUT_DIR, print_header, silence_stdout, verdict


def _score_by_geoid(tracts, j311, jhpd, jvac, acs):
    """Run one pipeline pass and return a GEOID→risk_score Series."""
    with silence_stdout():
        tdf = aggregate(tracts, j311, jhpd, jvac, acs)
        scores, _ = run_rank_composite(tdf)
    # run_rank_composite indexes by the positional rows of tdf — map back to GEOID
    return pd.Series(scores.values, index=tdf.loc[scores.index, "GEOID"].values)


def run(n_boot: int = 200, seed: int = 42) -> dict:
    print_header(f"Test 3 — Bootstrap confidence intervals  (B = {n_boot})")

    with silence_stdout():
        tracts = load_tracts()
        gdf_311 = load_311(DATA_DIR / "311_data.csv")
        gdf_hpd = load_hpd(DATA_DIR / "hpd_violations.csv")
        gdf_vacate = load_vacate_orders(DATA_DIR / "Order_To_Repair.csv")
        acs = load_acs()
        joined_311 = join_311_to_tracts(gdf_311, tracts)
        joined_hpd = join_hpd_to_tracts(gdf_hpd, tracts)
        joined_vacate = join_vacate_to_tracts(gdf_vacate, tracts)

    base = _score_by_geoid(tracts, joined_311, joined_hpd, joined_vacate, acs)

    # Collect into a list of arrays, then build the DataFrame in one shot.
    # Per-iteration DataFrame column assignment fragments the block manager
    # and triggers PerformanceWarning at B≥100.
    samples = np.empty((len(base), n_boot), dtype=float)
    rng = np.random.default_rng(seed)
    for b in range(n_boot):
        j311 = joined_311.sample(
            frac=1.0, replace=True, random_state=int(rng.integers(1 << 30))
        )
        jhpd = joined_hpd.sample(
            frac=1.0, replace=True, random_state=int(rng.integers(1 << 30))
        )
        jvac = joined_vacate.sample(
            frac=1.0, replace=True, random_state=int(rng.integers(1 << 30))
        )
        s = _score_by_geoid(tracts, j311, jhpd, jvac, acs)
        samples[:, b] = s.reindex(base.index).values
        if (b + 1) % 20 == 0 or b + 1 == n_boot:
            print(f"  bootstrap {b + 1}/{n_boot}")

    ci_low = pd.Series(np.nanquantile(samples, 0.05, axis=1), index=base.index)
    ci_high = pd.Series(np.nanquantile(samples, 0.95, axis=1), index=base.index)
    ci_width = ci_high - ci_low

    out = (
        pd.DataFrame({
            "GEOID": base.index,
            "base_risk": base.values,
            "ci_low": ci_low.values,
            "ci_high": ci_high.values,
            "ci_width": ci_width.values,
        })
        .dropna()
    )

    path = OUTPUT_DIR / "validation_bootstrap_ci.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(path, index=False)

    median_w = float(out["ci_width"].median())
    p75 = float(out["ci_width"].quantile(0.75))
    print(f"\nN tracts with CIs: {len(out):,}")
    print(f"Median 90% CI width: {median_w:.1f} points")
    print(f"  25th pct: {out['ci_width'].quantile(0.25):.1f}")
    print(f"  75th pct: {p75:.1f}")
    print(f"Wrote per-tract CIs → {path}")
    print(f"  {verdict(median_w < 15)} median CI tight enough to claim precision (< 15)")

    return {
        "median_ci_width": median_w,
        "p75_ci_width": p75,
        "n_bootstrap": n_boot,
        "output_path": str(path),
    }


if __name__ == "__main__":
    b = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    run(b)
