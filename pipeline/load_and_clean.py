import os
from pathlib import Path

import geopandas as gpd
import pandas as pd

from pipeline.sources import census, socrata

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"

# NYC Open Data (Socrata) dataset ids — fetched at build time via pipeline.sources.
DATASET_311 = "erm2-nwe9"     # 311 Service Requests (2020-present)
DATASET_HPD = "wvxf-dwi5"     # Housing Maintenance Code Violations
DATASET_VACATE = "tb8q-a3ar"  # Order to Repair / Vacate Orders
DATASET_PLUTO = "64uk-42ks"   # PLUTO tax-lot data
SOCRATA_APP_TOKEN = os.environ.get("SOCRATA_APP_TOKEN")

# Default window for the (non-longitudinal) snapshot pipeline; the quarterly
# pipeline passes explicit per-quarter dates. Previously 311 was hardcoded to
# 2024+ and HPD/vacate were all-time; now every source shares one windowed,
# API-backed path. `end=None` means open-ended (up to the latest record).
DEFAULT_START = "2024-01-01"
DEFAULT_END = None

HOUSING_COMPLAINT_TYPES = {
    "HEAT/HOT WATER",
    "PLUMBING",
    "PAINT/PLASTER",
    "GENERAL CONSTRUCTION",
    "WATER LEAK",
    "DOOR/WINDOW",
    "ELECTRIC",
    "ELEVATOR",
    "FLOORING/STAIRS",
    "UNSANITARY CONDITION",
    "MOLD",
    "APPLIANCE",
    "VENTILATION",
    "FIRE SAFETY",
    "LEAD",
    "ASBESTOS",
    "ROOFTOP",
    "BASEMENT",
    "STRUCTURAL",
}

NYC_BBOX = {"lat_min": 40.4, "lat_max": 40.95, "lon_min": -74.3, "lon_max": -73.65}


def _norm(name: str) -> str:
    return name.strip().lower().replace(" ", "_")


def _sniff_columns(path) -> dict[str, str]:
    """Read just the header and return {normalized_name: original_name}.
    Lets each loader find its required columns regardless of casing/spacing."""
    raw_header = pd.read_csv(path, nrows=0)
    return {_norm(c): c for c in raw_header.columns}


def _filter_to_nyc(df: pd.DataFrame, lat_col: str, lon_col: str) -> pd.DataFrame:
    """Drop null/zero coordinates and filter to the NYC bounding box."""
    df = df.dropna(subset=[lat_col, lon_col])
    return df[
        (df[lat_col] != 0) & (df[lon_col] != 0)
        & df[lat_col].between(NYC_BBOX["lat_min"], NYC_BBOX["lat_max"])
        & df[lon_col].between(NYC_BBOX["lon_min"], NYC_BBOX["lon_max"])
    ]


def load_tracts():
    tracts = gpd.read_file(DATA_DIR / "nyct2020.shp")[
        ["GEOID", "BoroName", "NTAName", "geometry"]
    ]
    tracts["GEOID"] = tracts["GEOID"].astype(str)
    tracts = tracts.rename(columns={"BoroName": "borough", "NTAName": "neighborhood"})
    if tracts.crs and tracts.crs.to_epsg() != 4326:
        tracts = tracts.to_crs(epsg=4326)
    return tracts


def load_council_districts() -> gpd.GeoDataFrame | None:
    """City Council district polygons (data/nycc.geojson, NYC Open Data
    dataset 872g-cjhh). Optional input: returns None with a warning when the
    file is absent so the pipeline stays runnable without it."""
    path = DATA_DIR / "nycc.geojson"
    if not path.exists():
        print(f"[warn] {path} missing — council districts will not be joined.\n"
              "       Download: https://data.cityofnewyork.us/resource/872g-cjhh.geojson")
        return None
    districts = gpd.read_file(path)
    col = next(
        (c for c in districts.columns if c.lower() in ("coundist", "coun_dist")), None
    )
    if col is None:
        raise ValueError(f"no district-number column in {path}: {list(districts.columns)}")
    districts = districts.rename(columns={col: "council_district"})[
        ["council_district", "geometry"]
    ]
    districts["council_district"] = districts["council_district"].astype(int)
    if districts.crs and districts.crs.to_epsg() != 4326:
        districts = districts.to_crs(epsg=4326)
    return districts


def load_311(start: str = DEFAULT_START, end: str | None = DEFAULT_END,
             borough: str | None = None) -> gpd.GeoDataFrame:
    """Housing 311 service requests from Socrata (erm2-nwe9), filtered server-side
    to housing complaint types and created_date in [start, end). Returns
    GeoDataFrame[complaint_type, closure_time_days, geometry] — the contract
    pipeline.aggregate expects. `borough` (uppercase name) is optional; None =
    citywide."""
    where = f"created_date >= '{start}'"
    if end:
        where += f" AND created_date < '{end}'"
    where += f" AND complaint_type in ({socrata.in_list(sorted(HOUSING_COMPLAINT_TYPES))})"
    if borough:
        where += f" AND borough = '{borough.upper()}'"
    df = socrata.fetch(
        DATASET_311,
        select=("unique_key,complaint_type,created_date,closed_date,"
                "resolution_description,latitude,longitude"),
        where=where, order="created_date", app_token=SOCRATA_APP_TOKEN,
    )
    empty = gpd.GeoDataFrame(
        {"complaint_type": [], "closure_time_days": []},
        geometry=gpd.GeoSeries([], crs="EPSG:4326"),
    )
    if df.empty:
        return empty

    created = pd.to_datetime(df["created_date"], errors="coerce")
    closed = pd.to_datetime(df["closed_date"], errors="coerce")
    df = df.assign(closure_time_days=(closed - created).dt.total_seconds() / 86400)
    df = df.dropna(subset=["closure_time_days", "complaint_type"])
    df = df[df["closure_time_days"] >= 0.04]
    # Auto-close filter (matches the prior CSV loader): drop no-action / auto-closed
    # records that would otherwise inflate complaint_count -> accountability_gap.
    if "resolution_description" in df.columns:
        auto = df["resolution_description"].str.upper().str.contains(
            "NO ACTION|AUTO-CLOSE|AUTOMATICALLY CLOSED", na=False
        )
        df = df[~auto]
    df["latitude"] = pd.to_numeric(df["latitude"], errors="coerce")
    df["longitude"] = pd.to_numeric(df["longitude"], errors="coerce")
    df = _filter_to_nyc(df, "latitude", "longitude")
    if df.empty:
        return empty
    return gpd.GeoDataFrame(
        df[["closure_time_days", "complaint_type"]].reset_index(drop=True),
        geometry=gpd.points_from_xy(df["longitude"], df["latitude"]),
        crs="EPSG:4326",
    )


def load_hpd(start: str = DEFAULT_START, end: str | None = DEFAULT_END,
             borough: str | None = None) -> gpd.GeoDataFrame:
    """HPD Class C violations from Socrata (wvxf-dwi5), date-filtered on
    inspectiondate. The API exposes no lat/lon, so each violation is geocoded via
    a PLUTO bbl -> lat/lon lookup. Returns GeoDataFrame[geometry] (aggregate only
    counts violations per tract)."""
    where = f"class = 'C' AND inspectiondate >= '{start}'"
    if end:
        where += f" AND inspectiondate < '{end}'"
    if borough:
        where += f" AND boro = '{borough.upper()}'"
    df = socrata.fetch(
        DATASET_HPD, select="class,inspectiondate,boroid,block,lot",
        where=where, order="inspectiondate", app_token=SOCRATA_APP_TOKEN,
    )
    empty = gpd.GeoDataFrame(geometry=gpd.GeoSeries([], crs="EPSG:4326"))
    if df.empty:
        return empty
    df = _geocode_hpd(df)
    if df.empty:
        return empty
    return gpd.GeoDataFrame(
        geometry=gpd.points_from_xy(df["longitude"], df["latitude"]),
        crs="EPSG:4326",
    )


def _geocode_hpd(df: pd.DataFrame) -> pd.DataFrame:
    """Attach latitude/longitude to HPD violation rows via a PLUTO bbl lookup
    and filter to the NYC bounding box. Expects boroid/block/lot columns; any
    other columns (e.g. inspectiondate) are preserved on the returned frame."""
    bbl_map = _pluto_bbl_latlon()
    lats, lons = [], []
    for boroid, block, lot in df[["boroid", "block", "lot"]].itertuples(index=False):
        try:
            ll = bbl_map.get(f"{int(boroid)}{int(block):05d}{int(lot):04d}")
        except (TypeError, ValueError):
            ll = None
        lats.append(ll[0] if ll else None)
        lons.append(ll[1] if ll else None)
    df = df.assign(latitude=lats, longitude=lons).dropna(subset=["latitude", "longitude"])
    return _filter_to_nyc(df, "latitude", "longitude")


def load_hpd_with_dates(
    cutoff_date: str, start: str = DEFAULT_START, end: str | None = DEFAULT_END,
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """Like load_hpd, but preserves inspectiondate to split violations by time.

    Fetches HPD Class C violations from Socrata over [start, end), geocodes them
    via PLUTO, then partitions on cutoff_date into (pre_gdf, post_gdf) — the
    contract the temporal-validation tests depend on. Each side is a
    GeoDataFrame[geometry]; with end=None, post-cutoff spans cutoff..latest."""
    where = f"class = 'C' AND inspectiondate >= '{start}'"
    if end:
        where += f" AND inspectiondate < '{end}'"
    df = socrata.fetch(
        DATASET_HPD, select="class,inspectiondate,boroid,block,lot",
        where=where, order="inspectiondate", app_token=SOCRATA_APP_TOKEN,
    )
    empty = gpd.GeoDataFrame(geometry=gpd.GeoSeries([], crs="EPSG:4326"))
    if df.empty:
        return empty, empty
    df = df.copy()
    df["inspectiondate"] = pd.to_datetime(df["inspectiondate"], errors="coerce")
    df = df.dropna(subset=["inspectiondate"])
    df = _geocode_hpd(df)
    if df.empty:
        return empty, empty

    cutoff = pd.to_datetime(cutoff_date)

    def to_gdf(sub: pd.DataFrame) -> gpd.GeoDataFrame:
        return gpd.GeoDataFrame(
            geometry=gpd.points_from_xy(sub["longitude"], sub["latitude"]),
            crs="EPSG:4326",
        )

    return to_gdf(df[df["inspectiondate"] < cutoff]), to_gdf(df[df["inspectiondate"] >= cutoff])


def load_vacate_orders(start: str = DEFAULT_START,
                       end: str | None = DEFAULT_END) -> gpd.GeoDataFrame:
    """Vacate orders from Socrata (tb8q-a3ar), date-filtered on
    vacate_effective_date. Returns GeoDataFrame[vacated_units, geometry]. Citywide
    (the dataset is small; the spatial join assigns tracts downstream)."""
    where = f"vacate_effective_date >= '{start}'"
    if end:
        where += f" AND vacate_effective_date < '{end}'"
    df = socrata.fetch(
        DATASET_VACATE,
        select="number_of_vacated_units,latitude,longitude",
        where=where, order="vacate_effective_date", app_token=SOCRATA_APP_TOKEN,
    )
    if df.empty:
        return gpd.GeoDataFrame(
            {"vacated_units": []}, geometry=gpd.GeoSeries([], crs="EPSG:4326"),
        )
    df["latitude"] = pd.to_numeric(df["latitude"], errors="coerce")
    df["longitude"] = pd.to_numeric(df["longitude"], errors="coerce")
    df = _filter_to_nyc(df, "latitude", "longitude")
    df["vacated_units"] = pd.to_numeric(
        df["number_of_vacated_units"], errors="coerce"
    ).fillna(1)
    return gpd.GeoDataFrame(
        df[["vacated_units"]].reset_index(drop=True),
        geometry=gpd.points_from_xy(df["longitude"], df["latitude"]),
        crs="EPSG:4326",
    )


def _pluto_raw() -> pd.DataFrame:
    """Citywide PLUTO lots (bbl, lat/lon, yearbuilt, unitsres) from Socrata,
    cached. One pull serves both HPD geocoding and building-stock features."""
    df = socrata.fetch(
        DATASET_PLUTO, select="bbl,latitude,longitude,yearbuilt,unitsres",
        where="latitude IS NOT NULL AND longitude IS NOT NULL",
        order="bbl", app_token=SOCRATA_APP_TOKEN,
    )
    for col in ("latitude", "longitude", "yearbuilt", "unitsres"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _pluto_bbl_latlon() -> dict[str, tuple[float, float]]:
    """bbl (10-digit string) -> (lat, lon), for geocoding HPD violations."""
    df = _pluto_raw().dropna(subset=["latitude", "longitude"])
    out: dict[str, tuple[float, float]] = {}
    for bbl, lat, lon in df[["bbl", "latitude", "longitude"]].itertuples(index=False):
        try:
            out[str(int(float(bbl)))] = (float(lat), float(lon))
        except (TypeError, ValueError):
            continue
    return out


def load_pluto() -> gpd.GeoDataFrame:
    """Residential PLUTO lots from Socrata (64uk-42ks), cached. Building age and
    unit counts feed the per-tract building-stock features (median year built,
    pre-war / rent-stabilized-proxy unit shares). Returns
    GeoDataFrame[yearbuilt, unitsres, geometry]."""
    df = _pluto_raw().dropna(subset=["latitude", "longitude", "yearbuilt", "unitsres"])
    df = df[(df["unitsres"] > 0) & df["yearbuilt"].between(1800, 2030)]
    df = _filter_to_nyc(df, "latitude", "longitude")
    print(f"PLUTO residential lots: {len(df):,} (units: {df['unitsres'].sum():,.0f})")
    return gpd.GeoDataFrame(
        df[["yearbuilt", "unitsres"]].reset_index(drop=True),
        geometry=gpd.points_from_xy(df["longitude"], df["latitude"]),
        crs="EPSG:4326",
    )


def load_acs(year: int = 2022) -> pd.DataFrame:
    # Core + demographic variables
    #   B19013_001E median household income
    #   B08013_001E aggregate travel time to work
    #   B01003_001E total population
    #   B25001_001E housing units
    #   B17001_002E population below poverty line
    #   B02001_003E Black/African American alone (any ethnicity)
    #   B03003_003E Hispanic or Latino (any race)
    #   B05002_013E foreign-born
    #   B25070_010E renters paying >=50% income on rent
    #   B25070_001E total renters (denominator for rent burden)
    #   B23025_005E unemployed (civilian labor force)
    #   B23025_002E civilian labor force (denominator for unemployment)
    #   B15003_022E bachelor's degree holders (age 25+)
    #   B15003_001E total pop age 25+ (denominator for education)
    variables = [
        "B19013_001E", "B08013_001E", "B01003_001E", "B25001_001E",
        "B17001_002E", "B02001_003E", "B03003_003E", "B05002_013E",
        "B25070_010E", "B25070_001E", "B23025_005E", "B23025_002E",
        "B15003_022E", "B15003_001E",
    ]
    df = census.fetch_acs(year, variables)
    df = df.rename(columns={
        "B19013_001E": "median_income",
        "B08013_001E": "mean_commute_time",
        "B01003_001E": "population",
        "B25001_001E": "housing_units",
        "B17001_002E": "poverty_count",
        "B02001_003E": "black_count",
        "B03003_003E": "hispanic_count",
        "B05002_013E": "foreign_born_count",
        "B25070_010E": "rent_burdened_count",
        "B25070_001E": "renter_total",
        "B23025_005E": "unemployed_count",
        "B23025_002E": "labor_force",
        "B15003_022E": "bachelors_count",
        "B15003_001E": "pop_25_plus",
    })
    numeric_cols = [
        "median_income", "mean_commute_time", "population", "housing_units",
        "poverty_count", "black_count", "hispanic_count", "foreign_born_count",
        "rent_burdened_count", "renter_total", "unemployed_count", "labor_force",
        "bachelors_count", "pop_25_plus",
    ]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")
        # Treat Census null sentinel (-666666666) as NaN before taking ratios
        df[col] = df[col].where(df[col] >= 0, other=pd.NA)

    def safe_ratio(num, den):
        return (num / den).where(den > 0, other=pd.NA)

    df["poverty_rate"] = safe_ratio(df["poverty_count"], df["population"])
    df["pct_black"] = safe_ratio(df["black_count"], df["population"])
    df["pct_hispanic"] = safe_ratio(df["hispanic_count"], df["population"])
    df["pct_foreign_born"] = safe_ratio(df["foreign_born_count"], df["population"])
    df["rent_burden"] = safe_ratio(df["rent_burdened_count"], df["renter_total"])
    df["unemployment_rate"] = safe_ratio(df["unemployed_count"], df["labor_force"])
    df["pct_bachelors"] = safe_ratio(df["bachelors_count"], df["pop_25_plus"])

    keep_cols = [
        "GEOID", "median_income", "mean_commute_time", "population", "housing_units",
        "poverty_rate", "pct_black", "pct_hispanic", "pct_foreign_born",
        "rent_burden", "unemployment_rate", "pct_bachelors",
    ]
    df = df[keep_cols]
    df["GEOID"] = df["GEOID"].astype(str)
    print(f"ACS tracts loaded: {len(df):,}")
    return df


if __name__ == "__main__":
    tracts = load_tracts()
    print(f"Tracts: {len(tracts):,}")
    gdf_311 = load_311()
    print(f"311 records: {len(gdf_311):,}")
    gdf_hpd = load_hpd()
    print(f"HPD records: {len(gdf_hpd):,}")
    acs = load_acs()
    print(acs.head())
