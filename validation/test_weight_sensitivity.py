"""Test 4 — weight sensitivity via Dirichlet perturbation.

The composite uses hand-chosen weights (40/30/20/10). This test asks:
if we perturb those weights, does the overall ranking change meaningfully?

For each of n_iter trials we sample a new weight vector from a Dirichlet
centered on the base weights (concentration controls how tight the
perturbation is) and recompute the composite score. Kendall τ between
the base and perturbed rankings tells us how stable the ordering is.

Interpretation:
  Median τ ≥ 0.85 — ranking is robust to the exact weight choice
  5th-pct τ  ≥ 0.70 — even adversarial weight draws don't break it

This reads master.geojson — no re-aggregation needed.
"""
import sys

import numpy as np
from scipy.stats import kendalltau, rankdata

from pipeline.regression import COMPOSITE_WEIGHTS
from validation.utils import load_master_geojson, print_header, verdict


def run(n_iter: int = 1000, concentration: float = 50.0, seed: int = 42) -> dict:
    print_header(f"Test 4 — Weight sensitivity  (n = {n_iter})")
    gdf = load_master_geojson()
    features = list(COMPOSITE_WEIGHTS.keys())
    missing = [f for f in features if f not in gdf.columns]
    if missing:
        raise RuntimeError(f"master.geojson missing composite features: {missing}")

    base_w = np.array([COMPOSITE_WEIGHTS[f] for f in features], dtype=float)

    df = gdf[features].dropna()
    ranks = df[features].rank(pct=True).values  # (n_tracts, n_features) in [0, 1]
    base_composite = ranks @ base_w / base_w.sum()
    base_order = rankdata(-base_composite)  # higher composite → rank 1

    rng = np.random.default_rng(seed)
    taus = np.empty(n_iter)
    for i in range(n_iter):
        # Dirichlet centered on base_w; concentration scales its tightness
        w = rng.dirichlet(base_w * concentration)
        comp = ranks @ w / w.sum()
        new_order = rankdata(-comp)
        t, _ = kendalltau(base_order, new_order)
        taus[i] = t

    median_tau = float(np.median(taus))
    p05_tau = float(np.quantile(taus, 0.05))
    frac_robust = float(np.mean(taus > 0.85))

    print(f"Tracts scored: {len(df):,}")
    print(f"Features: {features}")
    print(f"Base weights: {base_w.round(2).tolist()}")
    print(f"Dirichlet concentration: {concentration}")
    print(f"\nMedian Kendall τ vs. base ranking: {median_tau:.3f}")
    print(f"5th-pct τ (worst-case draws):      {p05_tau:.3f}")
    print(f"Fraction of draws with τ > 0.85:   {frac_robust:.1%}")
    print(f"  {verdict(median_tau > 0.85)} robust to weight perturbation (median τ > 0.85)")
    print(f"  {verdict(p05_tau > 0.70)} stable even under adversarial weights (5th-pct > 0.70)")

    return {
        "median_tau": median_tau,
        "p05_tau": p05_tau,
        "frac_robust": frac_robust,
        "n_iter": n_iter,
    }


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
    run(n)
