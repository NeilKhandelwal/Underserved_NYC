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

import geopandas as gpd
import pandas as pd
from scipy.stats import spearmanr

from pipeline.load_and_clean import (
    DATA_DIR, _filter_to_nyc, _norm, _sniff_columns,
    load_311, load_acs, load_tracts, load_vacate_orders,
)
from pipeline.aggregate import aggregate
from pipeline.regression import run_rank_composite
from pipeline.spatial_join import (
    join_311_to_tracts, join_hpd_to_tracts, join_vacate_to_tracts,
)
from validation.utils import print_header, silence_stdout, verdict

DEFAULT_CUTOFF = "2024-10-01"  # leaves ~6 months of "future" data


def _load_hpd_with_dates(path, cutoff_date):
    """Like pipeline.load_and_clean.load_hpd, but preserves the inspection
    date so we can split violations by time. Returns (pre_gdf, post_gdf).
    """
    norm_to_orig = _sniff_columns(path)

    def find(*keywords):
        for kw in keywords:
            for k, v in norm_to_orig.items():
                if kw in k:
                    return v
        return None

    class_orig = find("class", "violationclass")
    lat_orig = find("latitude")
    lon_orig = find("longitude")
    date_orig = find(
        "inspectiondate", "novissueddate", "certifieddate",
        "originalcertifybydate", "approveddate",
    )
    if date_orig is None:
        raise RuntimeError(
            "Could not find an HPD date column for temporal split. "
            f"Columns: {list(norm_to_orig.keys())[:30]}"
        )
    if lat_orig is None or lon_orig is None:
        raise RuntimeError("Missing lat/lon in HPD data.")

    keep = [c for c in [class_orig, lat_orig, lon_orig, date_orig] if c]
    class_col = _norm(class_orig) if class_orig else None
    lat_col = _norm(lat_orig)
    lon_col = _norm(lon_orig)
    date_col = _norm(date_orig)

    df = pd.read_csv(path, usecols=keep, low_memory=False)
    df.columns = [_norm(c) for c in df.columns]

    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    if class_col:
        df = df[df[class_col].str.upper().str.strip() == "C"]
    df = df.dropna(subset=[date_col])
    df = _filter_to_nyc(df, lat_col, lon_col)

    cutoff = pd.to_datetime(cutoff_date)
    pre = df[df[date_col] < cutoff]
    post = df[df[date_col] >= cutoff]

    def to_gdf(sub):
        return gpd.GeoDataFrame(
            geometry=gpd.points_from_xy(sub[lon_col], sub[lat_col]),
            crs="EPSG:4326",
        )
    return to_gdf(pre), to_gdf(post)


def run(cutoff_date: str = DEFAULT_CUTOFF) -> dict:
    print_header(f"Test 2 — Temporal split  (cutoff: {cutoff_date})")

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
