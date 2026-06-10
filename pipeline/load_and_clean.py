import geopandas as gpd
import pandas as pd
import requests
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"

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


def load_311(path) -> gpd.GeoDataFrame:
    norm_to_orig = _sniff_columns(path)

    def find(*keywords):
        for kw in keywords:
            for k, v in norm_to_orig.items():
                if kw in k:
                    return v
        return None

    complaint_orig = find("complaint_type", "complaint", "problem")
    created_orig = find("created_date", "created")
    closed_orig = find("closed_date", "closed")
    lat_orig = find("latitude")
    lon_orig = find("longitude")
    res_orig = find("resolution_description", "resolution")

    if None in (complaint_orig, created_orig, closed_orig, lat_orig, lon_orig):
        raise ValueError(
            f"Missing required columns. Found: {list(norm_to_orig.keys())}"
        )

    keep_orig = [complaint_orig, created_orig, closed_orig, lat_orig, lon_orig]
    if res_orig:
        keep_orig.append(res_orig)

    # Normalized names are deterministic from originals — resolve once.
    complaint_col = _norm(complaint_orig)
    created_col = _norm(created_orig)
    closed_col = _norm(closed_orig)
    lat_col = _norm(lat_orig)
    lon_col = _norm(lon_orig)
    res_col = _norm(res_orig) if res_orig else None

    print("Loading 311 in chunks (filtering to housing types only)...")
    chunks = []
    for chunk in pd.read_csv(path, usecols=keep_orig, chunksize=50_000, low_memory=False):
        chunk.columns = [_norm(c) for c in chunk.columns]
        chunk = chunk[chunk[complaint_col].str.upper().isin(HOUSING_COMPLAINT_TYPES)]
        chunks.append(chunk)
    df = pd.concat(chunks, ignore_index=True)
    df = df.rename(columns={complaint_col: "complaint_type"})
    print(f"After housing filter: {len(df):,} rows")

    if len(df) == 0:
        print("WARNING: 0 rows matched housing filter. Sample complaint types in raw data:")
        sample = pd.read_csv(path, usecols=[complaint_orig], nrows=500)
        print(sorted(sample.iloc[:, 0].dropna().unique()))

    df[created_col] = pd.to_datetime(df[created_col], errors="coerce", format="mixed")
    df[closed_col] = pd.to_datetime(df[closed_col], errors="coerce", format="mixed")
    df = df.dropna(subset=[created_col, closed_col])
    # Keep only 2024-present to control dataset size
    df = df[df[created_col].dt.year >= 2024]
    df["closure_time_days"] = (df[closed_col] - df[created_col]).dt.total_seconds() / 86400
    print(f"After date filter (2024+): {len(df):,} rows")
    df = df[df["closure_time_days"] >= 0.04]

    if res_col and res_col in df.columns:
        no_action = df[res_col].str.upper().str.contains(
            "NO ACTION|AUTO-CLOSE|AUTOMATICALLY CLOSED", na=False
        )
        df = df[~no_action]
        print(f"After auto-close filter: {len(df):,} rows")

    df = _filter_to_nyc(df, lat_col, lon_col)
    print(f"After geo filter: {len(df):,} rows")

    return gpd.GeoDataFrame(
        df[["closure_time_days", "complaint_type"]].reset_index(drop=True),
        geometry=gpd.points_from_xy(df[lon_col], df[lat_col]),
        crs="EPSG:4326",
    )


def load_hpd(path) -> gpd.GeoDataFrame:
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
    if lat_orig is None or lon_orig is None:
        raise ValueError("Could not find latitude/longitude columns in HPD data")

    keep_orig = [c for c in [class_orig, lat_orig, lon_orig] if c]
    class_col = _norm(class_orig) if class_orig else None
    lat_col = _norm(lat_orig)
    lon_col = _norm(lon_orig)

    print("Loading HPD in chunks (Class C only)...")
    chunks = []
    for chunk in pd.read_csv(path, usecols=keep_orig, chunksize=50_000, low_memory=False):
        chunk.columns = [_norm(c) for c in chunk.columns]
        if class_col:
            chunk = chunk[chunk[class_col].str.upper().str.strip() == "C"]
        chunks.append(chunk)
    df = pd.concat(chunks, ignore_index=True)
    print(f"HPD Class C violations: {len(df):,} rows")

    df = _filter_to_nyc(df, lat_col, lon_col)
    print(f"HPD after geo filter: {len(df):,} rows")

    return gpd.GeoDataFrame(
        geometry=gpd.points_from_xy(df[lon_col], df[lat_col]),
        crs="EPSG:4326",
    )


def load_vacate_orders(path) -> gpd.GeoDataFrame:
    norm_to_orig = _sniff_columns(path)

    def find(*keywords):
        for kw in keywords:
            for k, v in norm_to_orig.items():
                if kw in k:
                    return v
        return None

    lat_orig = find("latitude")
    lon_orig = find("longitude")
    units_orig = find("vacated_units", "units")
    if lat_orig is None or lon_orig is None:
        raise ValueError("Could not find latitude/longitude columns in vacate orders data")

    keep_orig = [c for c in [lat_orig, lon_orig, units_orig] if c]
    lat_col = _norm(lat_orig)
    lon_col = _norm(lon_orig)
    units_col = _norm(units_orig) if units_orig else None

    df = pd.read_csv(path, usecols=keep_orig, low_memory=False)
    df.columns = [_norm(c) for c in df.columns]

    df[lat_col] = pd.to_numeric(df[lat_col], errors="coerce")
    df[lon_col] = pd.to_numeric(df[lon_col], errors="coerce")
    df = _filter_to_nyc(df, lat_col, lon_col)

    if units_col:
        df[units_col] = pd.to_numeric(df[units_col], errors="coerce").fillna(1)
        df = df.rename(columns={units_col: "vacated_units"})
    else:
        df["vacated_units"] = 1

    gdf = gpd.GeoDataFrame(
        df[["vacated_units"]].reset_index(drop=True),
        geometry=gpd.points_from_xy(df[lon_col], df[lat_col]),
        crs="EPSG:4326",
    )
    print(f"Vacate orders loaded: {len(gdf):,} records")
    return gdf


def load_pluto() -> gpd.GeoDataFrame:
    """Load NYC PLUTO tax-lot data, filtered to residential lots.

    Source: NYC Open Data — "Primary Land Use Tax Lot Output (PLUTO)".
    Save the CSV as one of (the loader auto-detects):
      data/pluto.csv
      data/pluto_*.csv         (e.g., pluto_24v3.csv)
      data/PLUTO*.csv

    Only `latitude`, `longitude`, `yearbuilt`, and `unitsres` are kept —
    enough to compute median building age and pre-war unit share per tract.
    Building age is a structural predictor of HPD violations and 311
    complaints (heat, plumbing, plaster) that's largely orthogonal to
    demographic composition.
    """
    candidates = [DATA_DIR / "pluto.csv"] + sorted(DATA_DIR.glob("pluto_*.csv")) \
        + sorted(DATA_DIR.glob("PLUTO*.csv"))
    path = next((p for p in candidates if p.exists()), None)
    if path is None:
        raise FileNotFoundError(
            "PLUTO not found. Download 'Primary Land Use Tax Lot Output "
            "(PLUTO)' from NYC Open Data as CSV and save as:\n"
            f"  {DATA_DIR / 'pluto.csv'}"
        )

    norm = {c.strip().lower(): c for c in pd.read_csv(path, nrows=0).columns}

    def need(*aliases):
        for a in aliases:
            if a in norm:
                return norm[a]
        return None

    lat_orig = need("latitude")
    lon_orig = need("longitude")
    year_orig = need("yearbuilt", "year_built")
    units_orig = need("unitsres", "units_res", "residential_units")
    if None in (lat_orig, lon_orig, year_orig, units_orig):
        raise ValueError(
            f"PLUTO missing required columns. Found: {list(norm.keys())[:30]}"
        )

    lat_col = lat_orig.strip().lower()
    lon_col = lon_orig.strip().lower()
    year_col = year_orig.strip().lower()
    units_col = units_orig.strip().lower()

    print(f"Loading PLUTO from {path.name} (residential lots only)...")
    chunks = []
    for chunk in pd.read_csv(
        path, usecols=[lat_orig, lon_orig, year_orig, units_orig],
        chunksize=100_000, low_memory=False,
    ):
        chunk.columns = chunk.columns.str.strip().str.lower()
        chunk[year_col] = pd.to_numeric(chunk[year_col], errors="coerce")
        chunk[units_col] = pd.to_numeric(chunk[units_col], errors="coerce")
        chunk = chunk.dropna(subset=[lat_col, lon_col, year_col, units_col])
        chunk = chunk[
            (chunk[units_col] > 0) & chunk[year_col].between(1800, 2030)
        ]
        chunk = _filter_to_nyc(chunk, lat_col, lon_col)
        chunks.append(
            chunk.rename(columns={
                lat_col: "lat", lon_col: "lon",
                year_col: "yearbuilt", units_col: "unitsres",
            })[["lat", "lon", "yearbuilt", "unitsres"]]
        )

    df = pd.concat(chunks, ignore_index=True)
    print(f"PLUTO residential lots: {len(df):,} (units: {df['unitsres'].sum():,.0f})")

    return gpd.GeoDataFrame(
        df[["yearbuilt", "unitsres"]].reset_index(drop=True),
        geometry=gpd.points_from_xy(df["lon"], df["lat"]),
        crs="EPSG:4326",
    )


def load_acs() -> pd.DataFrame:
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
    url = (
        "https://api.census.gov/data/2022/acs/acs5"
        f"?get={','.join(variables)}"
        "&for=tract:*&in=state:36&in=county:005,047,061,081,085"
    )
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    df = pd.DataFrame(data[1:], columns=data[0])
    df["GEOID"] = df["state"] + df["county"] + df["tract"]
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
    gdf_311 = load_311(DATA_DIR / "311_data.csv")
    print(f"311 records: {len(gdf_311):,}")
    gdf_hpd = load_hpd(DATA_DIR / "hpd_violations.csv")
    print(f"HPD records: {len(gdf_hpd):,}")
    acs = load_acs()
    print(acs.head())
