import geopandas as gpd
from pipeline.load_and_clean import load_tracts, load_311, load_hpd


def join_311_to_tracts(gdf_311: gpd.GeoDataFrame, tracts: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    joined = gpd.sjoin(gdf_311, tracts[["GEOID", "geometry"]], how="inner", predicate="within")
    joined = joined.drop(columns=["index_right"])
    print(f"311 records after spatial join: {len(joined):,}")
    return joined


def join_hpd_to_tracts(gdf_hpd: gpd.GeoDataFrame, tracts: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    joined = gpd.sjoin(gdf_hpd, tracts[["GEOID", "geometry"]], how="inner", predicate="within")
    joined = joined.drop(columns=["index_right"])
    print(f"HPD records after spatial join: {len(joined):,}")
    return joined


def join_vacate_to_tracts(gdf_vacate: gpd.GeoDataFrame, tracts: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    joined = gpd.sjoin(gdf_vacate, tracts[["GEOID", "geometry"]], how="inner", predicate="within")
    joined = joined.drop(columns=["index_right"])
    print(f"Vacate order records after spatial join: {len(joined):,}")
    return joined


def join_pluto_to_tracts(
    gdf_pluto: gpd.GeoDataFrame, tracts: gpd.GeoDataFrame
) -> gpd.GeoDataFrame:
    """Spatial-join PLUTO residential lots to tracts.

    PLUTO is ~860k rows so this is the slowest join in the pipeline
    (~30s on a typical laptop). Done once per pipeline run."""
    joined = gpd.sjoin(
        gdf_pluto, tracts[["GEOID", "geometry"]], how="inner", predicate="within"
    ).drop(columns=["index_right"])
    print(f"PLUTO lots after spatial join: {len(joined):,}")
    return joined



if __name__ == "__main__":
    tracts = load_tracts()
    gdf_311 = load_311()
    gdf_hpd = load_hpd()

    joined_311 = join_311_to_tracts(gdf_311, tracts)
    joined_hpd = join_hpd_to_tracts(gdf_hpd, tracts)

    print(joined_311.head())
    print(joined_hpd.head())
