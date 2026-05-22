import geopandas as gpd
import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression
from pipeline.load_and_clean import load_tracts, load_311, load_hpd, load_vacate_orders, load_acs, load_pluto, DATA_DIR
from pipeline.spatial_join import join_311_to_tracts, join_hpd_to_tracts, join_vacate_to_tracts, join_pluto_to_tracts


def aggregate(tracts: gpd.GeoDataFrame, joined_311: gpd.GeoDataFrame,
              joined_hpd: gpd.GeoDataFrame, joined_vacate: gpd.GeoDataFrame,
              acs: pd.DataFrame,
              joined_pluto: gpd.GeoDataFrame | None = None) -> gpd.GeoDataFrame:
    avg_closure = (
        joined_311.groupby("GEOID")["closure_time_days"]
        .mean()
        .rename("avg_closure_time")
    )

    # Fix 1 — per-complaint-type normalization.
    # Heat closes in days, mold in months. A tract's raw avg_closure_time conflates
    # "agency is slow here" with "this tract files mostly slow-by-design complaints."
    # Divide each record's closure time by the citywide MEDIAN for its complaint type;
    # the per-tract mean of that ratio is unitless responsiveness:
    #   1.0 = exactly typical for this tract's complaint mix
    #   1.5 = 50% slower than typical
    type_median = joined_311.groupby("complaint_type")["closure_time_days"].median()
    joined_311 = joined_311.copy()
    joined_311["closure_ratio"] = (
        joined_311["closure_time_days"] / joined_311["complaint_type"].map(type_median)
    )
    avg_closure_ratio = (
        joined_311.groupby("GEOID")["closure_ratio"]
        .mean()
        .rename("avg_closure_ratio")
    )

    complaint_counts = (
        joined_311.groupby("GEOID").size().rename("complaint_count")
    )

    hpd_counts = (
        joined_hpd.groupby("GEOID").size().rename("violation_count")
    )

    # Sum vacated units per tract for severity weighting
    vacate_units = (
        joined_vacate.groupby("GEOID")["vacated_units"].sum().rename("vacated_units")
    )

    tract_df = tracts[["GEOID", "borough", "neighborhood", "geometry"]].copy()
    tract_df = tract_df.merge(avg_closure, on="GEOID", how="left")
    tract_df = tract_df.merge(avg_closure_ratio, on="GEOID", how="left")
    tract_df = tract_df.merge(complaint_counts, on="GEOID", how="left")
    tract_df = tract_df.merge(hpd_counts, on="GEOID", how="left")
    tract_df = tract_df.merge(vacate_units, on="GEOID", how="left")
    acs_cols = [
        "GEOID", "median_income", "mean_commute_time", "population", "housing_units",
        "poverty_rate", "pct_black", "pct_hispanic", "pct_foreign_born",
        "rent_burden", "unemployment_rate", "pct_bachelors",
    ]
    tract_df = tract_df.merge(
        acs[[c for c in acs_cols if c in acs.columns]],
        on="GEOID", how="left"
    )

    tract_df["complaint_count"] = tract_df["complaint_count"].fillna(0)
    tract_df["violation_count"] = tract_df["violation_count"].fillna(0)
    tract_df["vacated_units"] = tract_df["vacated_units"].fillna(0)

    if joined_pluto is not None and len(joined_pluto):
        # Median year built per tract — unweighted across residential lots.
        # Lots with very different unit counts (a brownstone vs. a 200-unit
        # tower) get equal weight here; that's deliberate, since age
        # heterogeneity matters for typical-stock characterization.
        median_year = (
            joined_pluto.groupby("GEOID")["yearbuilt"].median()
            .rename("median_year_built")
        )
        # Pre-war unit share — units in buildings completed before 1947
        # (NYC Multiple Dwelling Law cutoff for "old-law" / pre-war stock).
        # Rent-stabilized proxy — units in pre-1974 buildings with ≥6 units.
        # The Emergency Tenant Protection Act of 1974 made any building
        # built before then with 6+ units presumptively rent-stabilized
        # (modulo opt-outs and conversions). Doesn't capture 421-a opt-ins
        # or J-51 enrollments, but a reasonable bulk proxy when the DOF
        # building-level list isn't available in structured form.
        pluto = joined_pluto.copy()
        pluto["prewar_units"] = pluto["unitsres"].where(pluto["yearbuilt"] < 1947, 0)
        pluto["rent_stab_proxy_units"] = pluto["unitsres"].where(
            (pluto["yearbuilt"] < 1974) & (pluto["unitsres"] >= 6), 0
        )
        agg = (
            pluto.groupby("GEOID")
            .agg(prewar_units=("prewar_units", "sum"),
                 rent_stab_proxy_units=("rent_stab_proxy_units", "sum"),
                 total_pluto_units=("unitsres", "sum"))
        )
        agg["pct_prewar_units"] = (
            agg["prewar_units"] / agg["total_pluto_units"]
        ).clip(0, 1)
        agg["pct_rent_stab_proxy"] = (
            agg["rent_stab_proxy_units"] / agg["total_pluto_units"]
        ).clip(0, 1)
        tract_df = tract_df.merge(median_year, on="GEOID", how="left")
        tract_df = tract_df.merge(
            agg[["pct_prewar_units", "pct_rent_stab_proxy"]],
            on="GEOID", how="left",
        )
    else:
        tract_df["median_year_built"] = pd.NA
        tract_df["pct_prewar_units"] = pd.NA
        tract_df["pct_rent_stab_proxy"] = pd.NA

    # Replace Census API null sentinel (-666666666) with NaN
    numeric_acs_cols = [
        "median_income", "mean_commute_time", "population", "housing_units",
        "poverty_rate", "pct_black", "pct_hispanic", "pct_foreign_born",
        "rent_burden", "unemployment_rate", "pct_bachelors",
    ]
    for col in numeric_acs_cols:
        if col in tract_df.columns:
            tract_df[col] = tract_df[col].where(tract_df[col] >= 0, other=pd.NA)

    tract_df = tract_df[tract_df["population"] > 0]
    tract_df = tract_df[tract_df["housing_units"] > 0]
    tract_df = tract_df.dropna(subset=["avg_closure_time", "median_income", "mean_commute_time",
                                        "population", "housing_units"])

    tract_df["complaint_rate"] = tract_df["complaint_count"] / tract_df["population"]
    tract_df["violation_rate"] = tract_df["violation_count"] / tract_df["housing_units"]
    tract_df["vacate_rate"] = tract_df["vacated_units"] / tract_df["housing_units"]

    # Income-adjust complaint_rate. Wealthier tracts have systematically different
    # 311 filing behavior (more access to alternatives, more savvy about reporting).
    # Without this correction, accountability_gap conflates "low neglect" with
    # "high reporting volume" in gentrifying tracts. We residualize complaint_rate
    # against log(median_income) and re-center on the citywide mean so the units
    # stay interpretable as "complaints per resident."
    mask = tract_df["median_income"].notna() & (tract_df["median_income"] > 0)
    X = np.log(tract_df.loc[mask, "median_income"].values).reshape(-1, 1)
    y = tract_df.loc[mask, "complaint_rate"].values
    income_model = LinearRegression().fit(X, y)
    predicted = income_model.predict(X)
    residuals = y - predicted
    city_mean = float(y.mean())
    adjusted = np.clip(residuals + city_mean, 1e-4, None)

    tract_df["complaint_rate_adjusted"] = np.nan
    tract_df.loc[mask, "complaint_rate_adjusted"] = adjusted
    tract_df["complaint_rate_adjusted"] = tract_df["complaint_rate_adjusted"].fillna(
        tract_df["complaint_rate"]
    )

    coef = float(income_model.coef_[0])
    direction = "more" if coef > 0 else "fewer"
    print(
        f"\nIncome→complaint_rate slope: {coef:+.5f} per log($) "
        f"→ wealthier tracts file {direction} 311s per capita (this is the bias being removed)"
    )

    # Fix 2 — triage-adjusted closure time.
    # HPD prioritizes high-violation tracts, so they get artificially fast response.
    # Without correction, avg_closure_time understates neglect in those tracts.
    # Residualize the type-adjusted closure ratio against violation_rate via OLS,
    # then recenter on the citywide mean. The result is "responsiveness compared to
    # other tracts with the same violation burden":
    #   citywide mean = exactly what triage predicts
    #   above       = slower than triage explains (real unresponsiveness)
    #   below       = faster than triage explains (genuinely responsive)
    triage_mask = tract_df["avg_closure_ratio"].notna() & tract_df["violation_rate"].notna()
    Xt = tract_df.loc[triage_mask, "violation_rate"].values.reshape(-1, 1)
    yt = tract_df.loc[triage_mask, "avg_closure_ratio"].values
    triage_model = LinearRegression().fit(Xt, yt)
    triage_pred = triage_model.predict(Xt)
    triage_city_mean = float(yt.mean())
    triage_adjusted = np.clip((yt - triage_pred) + triage_city_mean, 1e-4, None)

    tract_df["avg_closure_time_adjusted"] = np.nan
    tract_df.loc[triage_mask, "avg_closure_time_adjusted"] = triage_adjusted
    tract_df["avg_closure_time_adjusted"] = tract_df["avg_closure_time_adjusted"].fillna(
        tract_df["avg_closure_ratio"]
    )

    triage_coef = float(triage_model.coef_[0])
    direction = "faster" if triage_coef < 0 else "slower"
    print(
        f"Triage slope: violation_rate→closure_ratio = {triage_coef:+.4f} "
        f"→ high-violation tracts close {direction} (this is the bias being removed)"
    )

    # Severity-weighted violation rate: amplify tracts where violations escalated to vacate orders
    tract_df["weighted_violation_rate"] = tract_df["violation_rate"] * (1 + tract_df["vacate_rate"])
    # Accountability gap now uses the income-adjusted complaint rate
    tract_df["accountability_gap"] = (
        tract_df["weighted_violation_rate"]
        / (tract_df["complaint_rate_adjusted"] + 0.001)
    )

    print(f"Tracts with full data: {len(tract_df):,}")
    print(tract_df[["GEOID", "avg_closure_time", "complaint_rate",
                     "weighted_violation_rate", "accountability_gap",
                     "vacate_rate"]].describe())
    return tract_df


if __name__ == "__main__":
    tracts = load_tracts()
    gdf_311 = load_311(DATA_DIR / "311_data.csv")
    gdf_hpd = load_hpd(DATA_DIR / "hpd_violations.csv")
    gdf_vacate = load_vacate_orders(DATA_DIR / "Order_To_Repair.csv")
    gdf_pluto = load_pluto()
    acs = load_acs()

    joined_311 = join_311_to_tracts(gdf_311, tracts)
    joined_hpd = join_hpd_to_tracts(gdf_hpd, tracts)
    joined_vacate = join_vacate_to_tracts(gdf_vacate, tracts)
    joined_pluto = join_pluto_to_tracts(gdf_pluto, tracts)

    tract_df = aggregate(
        tracts, joined_311, joined_hpd, joined_vacate, acs, joined_pluto
    )
    print(tract_df.head())
