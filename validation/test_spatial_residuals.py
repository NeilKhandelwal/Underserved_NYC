"""Test 5 — spatial autocorrelation of RF residuals (Moran's I).

If residuals (risk_score − demographic_prediction) cluster spatially,
the model is missing a neighborhood-level covariate — neighboring tracts
shouldn't systematically share residual sign if the demographics alone
explained the geography of neglect. Ideally residuals are spatially
random (low |I|, non-significant p).

Interpretation:
  |I| < 0.10                — residuals are close to spatially random
  p_sim > 0.05               — null of spatial randomness not rejected
  strong significant positive I — the RF is missing a spatial predictor
                                  (add features like borough fixed effects,
                                  building age, NYCHA share, etc.)
"""
import sys

import numpy as np

from validation.utils import load_master_geojson, print_header, verdict


def run(k: int = 6, n_perm: int = 999) -> dict:
    try:
        from esda.moran import Moran
        from libpysal.weights import KNN
    except ImportError:
        print(
            "[SKIP] Moran's I requires libpysal + esda.\n"
            "  Install: pip install libpysal esda"
        )
        return {"skipped": True, "reason": "missing libpysal/esda"}

    print_header(f"Test 5 — Moran's I on residuals  (KNN k = {k}, perms = {n_perm})")

    gdf = load_master_geojson()
    if "risk_residual" not in gdf.columns:
        print(
            "[SKIP] risk_residual missing from master.geojson.\n"
            "  Run: python -m pipeline.demographic_analysis"
        )
        return {"skipped": True, "reason": "missing residuals"}

    g = gdf.dropna(subset=["risk_residual"]).reset_index(drop=True)
    # Compute centroids in a projected CRS (feet; NY State Plane) so KNN
    # distances are meaningful.
    cents = g.to_crs("EPSG:2263").geometry.centroid
    coords = np.column_stack([cents.x.values, cents.y.values])

    w = KNN.from_array(coords, k=k)
    w.transform = "r"

    m = Moran(g["risk_residual"].values, w, permutations=n_perm)

    print(f"N tracts:          {len(g):,}")
    print(f"Moran's I:         {m.I:+.4f}")
    print(f"Expected under H0: {m.EI:+.4f}")
    print(f"z-score (sim):     {m.z_sim:+.2f}")
    print(f"Pseudo-p (perm):   {m.p_sim:.4f}")
    magnitude_ok = abs(m.I) < 0.10
    p_ok = m.p_sim > 0.05
    print(
        f"  {verdict(magnitude_ok)} |I| < 0.10 "
        f"(residuals close to spatially random in magnitude)"
    )
    print(
        f"  {verdict(p_ok)} p > 0.05 (null of spatial randomness not rejected)"
    )
    if not (magnitude_ok and p_ok):
        print(
            "  → The RF residuals cluster spatially, meaning the demographic "
            "feature set leaves a neighborhood signature. Adding spatial "
            "features (borough fixed effects, building-age, NYCHA share, etc.) "
            "should improve the counterfactual."
        )

    return {
        "moran_I": float(m.I),
        "expected_I": float(m.EI),
        "z_sim": float(m.z_sim),
        "p_sim": float(m.p_sim),
        "n_tracts": int(len(g)),
    }


if __name__ == "__main__":
    k = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    run(k)
