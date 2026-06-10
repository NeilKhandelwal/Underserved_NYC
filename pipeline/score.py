import geopandas as gpd
from pipeline.load_and_clean import load_tracts, load_311, load_hpd, load_vacate_orders, load_acs, load_pluto, load_council_districts, DATA_DIR, PROJECT_ROOT
from pipeline.spatial_join import join_311_to_tracts, join_hpd_to_tracts, join_vacate_to_tracts, join_pluto_to_tracts
from pipeline.aggregate import aggregate
from pipeline.regression import run_rank_composite

OUTPUT_PATH = PROJECT_ROOT / "output" / "master.geojson"


def compute_scores(tract_df: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    df = tract_df.copy()
    scores, _ = run_rank_composite(df)
    df.loc[scores.index, "risk_score"] = scores
    df = df.dropna(subset=["risk_score"])
    print(f"\nFinal risk_score distribution:\n{df['risk_score'].describe().round(2)}")
    return df


def join_council_districts(tract_df: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Tag each tract with its City Council district (representative-point
    within join). No-op with a warning when data/nycc.geojson is absent."""
    districts = load_council_districts()
    if districts is None:
        return tract_df
    points = tract_df.copy()
    points["geometry"] = points.geometry.representative_point()
    joined = gpd.sjoin(points, districts, how="left", predicate="within")
    tract_df = tract_df.copy()
    # Float (not Int64) so the GeoJSON driver handles unmatched tracts as null;
    # the API layer coerces back to int.
    tract_df["council_district"] = joined["council_district"].astype(float).values
    n_missing = int(tract_df["council_district"].isna().sum())
    print(f"Joined council districts ({n_missing} tracts unmatched)")
    return tract_df


def export_geojson(tract_df: gpd.GeoDataFrame, path: str = OUTPUT_PATH):
    display_cols = [
        "GEOID", "borough", "neighborhood", "council_district", "geometry", "risk_score",
        "avg_closure_time", "avg_closure_ratio", "avg_closure_time_adjusted",
        "complaint_rate", "complaint_rate_adjusted",
        "violation_rate",
        "weighted_violation_rate", "vacate_rate", "accountability_gap",
        "median_income", "mean_commute_time", "population", "housing_units",
        "poverty_rate", "pct_black", "pct_hispanic", "pct_foreign_born",
        "rent_burden", "unemployment_rate", "pct_bachelors",
        "median_year_built", "pct_prewar_units", "pct_rent_stab_proxy",
    ]
    out = tract_df[[c for c in display_cols if c in tract_df.columns]].copy()
    out = out.set_crs("EPSG:4326", allow_override=True)
    out.to_file(path, driver="GeoJSON")
    print(f"Exported {len(out):,} tracts to {path}")


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

    scored_df = compute_scores(tract_df)
    scored_df = join_council_districts(scored_df)
    export_geojson(scored_df)
