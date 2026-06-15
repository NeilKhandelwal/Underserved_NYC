"""Cached, paged NYC Open Data (Socrata) client.

`fetch()` pulls a filtered slice (`$where`/`$select`) with pagination, retries
transient errors, and caches the result to data/cache/ keyed by the query, so
repeated and multi-quarter pulls don't re-hit the network. Set SOCRATA_APP_TOKEN
for a higher rate limit; it works without one.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import pandas as pd
import requests

BASE = "https://data.cityofnewyork.us/resource"
# pipeline/sources/socrata.py -> repo root is two parents up from the package.
CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "cache"
PAGE_SIZE = 50000
_RETRY_STATUS = {429, 500, 502, 503, 504}


def in_list(values) -> str:
    """SoQL `in(...)` clause body from string values, single-quote-escaped."""
    return ",".join("'" + str(v).replace("'", "''") + "'" for v in values)


def _cache_path(dataset: str, key: str) -> Path:
    digest = hashlib.sha1(key.encode()).hexdigest()[:16]
    return CACHE_DIR / f"{dataset}_{digest}.parquet"


def _get_with_retry(url: str, params: dict, headers: dict, tries: int = 5) -> list[dict]:
    for attempt in range(tries):
        resp = requests.get(url, params=params, headers=headers, timeout=120)
        if resp.status_code in _RETRY_STATUS and attempt < tries - 1:
            time.sleep(2 ** attempt)  # 1s, 2s, 4s, 8s
            continue
        resp.raise_for_status()
        return resp.json()
    resp.raise_for_status()  # exhausted retries on a retryable status
    return []


def fetch(dataset: str, *, select: str, where: str, order: str,
          app_token: str | None = None, page_size: int = PAGE_SIZE,
          max_pages: int = 10000, cache: bool = True) -> pd.DataFrame:
    """Return the selected columns for all rows matching `where` (paged).

    Cached to a parquet keyed by (dataset, select, where, order). Empty results
    are returned but not cached (cheap to re-pull, and parquet needs a schema).
    """
    key = json.dumps({"select": select, "where": where, "order": order}, sort_keys=True)
    path = _cache_path(dataset, key)
    if cache and path.exists():
        return pd.read_parquet(path)

    headers = {"X-App-Token": app_token} if app_token else {}
    rows: list[dict] = []
    for i in range(max_pages):
        batch = _get_with_retry(
            f"{BASE}/{dataset}.json",
            {"$select": select, "$where": where, "$order": order,
             "$limit": page_size, "$offset": i * page_size},
            headers,
        )
        rows.extend(batch)
        if len(batch) < page_size:
            break

    df = pd.DataFrame(rows)
    if cache and not df.empty:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path)
    return df
