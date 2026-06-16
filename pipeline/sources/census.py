"""Cached US Census ACS 5-year client.

Returns the raw variable columns for NYC tracts for a given ACS vintage; the
caller (pipeline.load_and_clean.load_acs) renames and derives ratios. Cached to
data/cache/ so re-runs and the per-quarter loop don't re-hit the Census API
(which is also occasionally flaky).
"""
from __future__ import annotations

import hashlib
import os
import time

import pandas as pd
import requests

from pipeline.sources.socrata import CACHE_DIR

# NYC counties: Bronx(005), Kings(047), New York(061), Queens(081), Richmond(085).
NYC_COUNTIES = "005,047,061,081,085"
_RETRY_STATUS = {429, 500, 502, 503, 504}
_KEY_HELP = (
    "Census ACS now requires a free API key. Get one at "
    "https://api.census.gov/data/key_signup.html and set CENSUS_API_KEY."
)


def fetch_acs(year: int, variables: list[str], *, cache: bool = True) -> pd.DataFrame:
    """Raw ACS5 table for NYC tracts: one column per variable plus a GEOID
    (state+county+tract). No type coercion or renaming — that's the caller's job.
    Requires a free CENSUS_API_KEY (the API redirects keyless requests to an
    HTML 'missing key' page)."""
    digest = hashlib.sha1(",".join(sorted(variables)).encode()).hexdigest()[:12]
    path = CACHE_DIR / f"acs5_{year}_{digest}.parquet"
    if cache and path.exists():
        return pd.read_parquet(path)

    api_key = os.environ.get("CENSUS_API_KEY")
    if not api_key:
        raise RuntimeError(_KEY_HELP)
    url = (
        f"https://api.census.gov/data/{year}/acs/acs5"
        f"?get={','.join(variables)}"
        f"&for=tract:*&in=state:36&in=county:{NYC_COUNTIES}&key={api_key}"
    )
    data = None
    for attempt in range(5):
        resp = requests.get(url, timeout=60)
        if resp.status_code in _RETRY_STATUS and attempt < 4:
            time.sleep(2 ** attempt)
            continue
        resp.raise_for_status()
        # Keyless/invalid-key requests 200-redirect to an HTML page, not JSON.
        if "json" not in resp.headers.get("content-type", "") or resp.url.endswith(".html"):
            # Redact the API key before surfacing the URL — error messages get
            # captured by logs/trackers, and the raw key shouldn't leak there.
            safe_url = resp.url.replace(api_key, "***") if api_key else resp.url
            raise RuntimeError(f"Census returned a non-JSON response ({safe_url}). {_KEY_HELP}")
        data = resp.json()
        break

    df = pd.DataFrame(data[1:], columns=data[0])
    df["GEOID"] = df["state"] + df["county"] + df["tract"]
    if cache and not df.empty:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path)
    return df
