"""Build the deployable serving bundle from already-computed artifacts.

The production API does NOT need geopandas, the 16 GB raw data, or even the
8 MB GeoJSON blob at request time. This step pre-bakes everything the future
FastAPI container serves into a small, self-contained ``serving/`` bundle:

    serving/data/tracts.json            per-GEOID records (no geometry)
    serving/data/citywide_stats.json    summary stats per numeric column
                                        (powers the "Nx vs city avg" panel)
    serving/data/timeseries.json        per-GEOID quarterly risk series (optional;
                                        copied if `make timeseries` has been run)
    serving/data/demographic_model.joblib   trained RF (copied)
    serving/data/demographic_model.json     model metadata (copied)
    serving/tiles/tracts.pmtiles        vector tiles for MapLibre (tippecanoe)

Inputs are the small files in ``output/`` produced by:
    python -m pipeline.score
    python -m pipeline.demographic_analysis

This script touches none of the raw data and has no third-party dependencies
(stdlib only), so it stays fast and trivially runnable in CI.
"""
from __future__ import annotations

import json
import math
import shutil
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output"
SERVING_DIR = PROJECT_ROOT / "serving"
DATA_OUT = SERVING_DIR / "data"
TILES_OUT = SERVING_DIR / "tiles"

GEOJSON_PATH = OUTPUT_DIR / "master.geojson"
MODEL_PATH = OUTPUT_DIR / "demographic_model.joblib"
MODEL_META_PATH = OUTPUT_DIR / "demographic_model.json"
DISTRICTS_OVERLAY_PATH = OUTPUT_DIR / "districts.geojson"
TIMESERIES_PATH = OUTPUT_DIR / "timeseries.json"

# Identity / label / non-metric columns excluded from numeric summary stats.
ID_COLS = {
    "GEOID", "borough", "neighborhood", "centroid_lon", "centroid_lat",
    "council_district",
}


def _is_number(v: object) -> bool:
    return (
        isinstance(v, (int, float))
        and not isinstance(v, bool)
        and not (isinstance(v, float) and math.isnan(v))
    )


def _quantile(sorted_vals: list[float], p: float) -> float:
    """Linear-interpolated quantile (matches numpy's default 'linear')."""
    n = len(sorted_vals)
    if n == 1:
        return sorted_vals[0]
    idx = p * (n - 1)
    lo = int(idx)
    hi = min(lo + 1, n - 1)
    frac = idx - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def _centroid(geometry: dict | None) -> tuple[float | None, float | None]:
    """Mean of all coordinate pairs — a cheap centroid good enough for map
    fly-to / panning (avoids a shapely dependency in this stdlib-only step)."""
    if not geometry:
        return None, None
    xs: list[float] = []
    ys: list[float] = []

    def walk(coords) -> None:
        if isinstance(coords, (list, tuple)):
            if coords and isinstance(coords[0], (int, float)):
                xs.append(coords[0])
                ys.append(coords[1])
            else:
                for c in coords:
                    walk(c)

    walk(geometry.get("coordinates"))
    if not xs:
        return None, None
    return sum(xs) / len(xs), sum(ys) / len(ys)


def build_tract_records(features: list[dict]) -> dict[str, dict]:
    """GEOID -> {all non-geometry properties + centroid for map fly-to}."""
    records: dict[str, dict] = {}
    for feat in features:
        props = dict(feat.get("properties", {}))
        geoid = props.get("GEOID")
        if geoid is None:
            continue
        lon, lat = _centroid(feat.get("geometry"))
        props["centroid_lon"] = lon
        props["centroid_lat"] = lat
        records[str(geoid)] = props
    return records


def build_citywide_stats(records: dict[str, dict]) -> dict[str, dict]:
    """Per-numeric-column summary stats used for tract-vs-city comparisons."""
    columns: dict[str, list[float]] = {}
    for props in records.values():
        for key, val in props.items():
            if key in ID_COLS or not _is_number(val):
                continue
            columns.setdefault(key, []).append(float(val))

    stats: dict[str, dict] = {}
    for key, vals in columns.items():
        sv = sorted(vals)
        n = len(sv)
        stats[key] = {
            "mean": sum(sv) / n,
            "median": _quantile(sv, 0.50),
            "min": sv[0],
            "p25": _quantile(sv, 0.25),
            "p75": _quantile(sv, 0.75),
            "max": sv[-1],
            "n": n,
        }
    return stats


def copy_optional(src: Path, dst: Path, *, missing_hint: str) -> bool:
    """Copy an optional, additive bundle artifact; warn-and-skip if absent.

    Returns True when copied. Used for the time series and district overlay —
    artifacts produced by separate, occasionally-run steps whose absence must not
    fail the core build.
    """
    if src.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        print(f"[copy]  {dst}")
        return True
    print(f"[skip]  {src} missing — {missing_hint}")
    return False


def build_pmtiles() -> bool:
    """Generate vector tiles via tippecanoe. Returns True on success.

    Missing tippecanoe is a warning, not a failure: the JSON bundle still
    lets the API answer everything except the map layer, and tiles can be
    generated later once tippecanoe is installed.
    """
    if shutil.which("tippecanoe") is None:
        print(
            "\n[skip] tippecanoe not found — vector tiles not generated.\n"
            "       Install it and re-run to produce serving/tiles/tracts.pmtiles:\n"
            "         macOS:  brew install tippecanoe\n"
            "         linux:  https://github.com/felt/tippecanoe#installation\n"
        )
        return False

    TILES_OUT.mkdir(parents=True, exist_ok=True)
    out = TILES_OUT / "tracts.pmtiles"
    cmd = [
        "tippecanoe",
        "-o", str(out),
        "-l", "tracts",
        # Tract-level map: cap at z13 (matches the frontend maxZoom) so edges
        # stay crisp up to the cap without storing building-level precision.
        "--minimum-zoom=9",
        "--maximum-zoom=13",
        "--projection=EPSG:4326",
        "--drop-densest-as-needed",
        "--no-tile-size-limit",
        "--quiet",
        "--no-progress-indicator",
        "--force",
        str(GEOJSON_PATH),
    ]
    print("\n[tiles] running tippecanoe ...")
    subprocess.run(cmd, check=True)
    print(f"[tiles] wrote {out}  ({out.stat().st_size / 1e6:.1f} MB)")
    return True


def main() -> None:
    for path in (GEOJSON_PATH, MODEL_PATH, MODEL_META_PATH):
        if not path.exists():
            raise SystemExit(
                f"Missing artifact: {path}\n"
                "Run the pipeline first:\n"
                "  python -m pipeline.score\n"
                "  python -m pipeline.demographic_analysis"
            )

    DATA_OUT.mkdir(parents=True, exist_ok=True)

    print(f"[read]  {GEOJSON_PATH}")
    with open(GEOJSON_PATH) as f:
        geojson = json.load(f)
    features = geojson.get("features", [])

    records = build_tract_records(features)
    stats = build_citywide_stats(records)

    tracts_path = DATA_OUT / "tracts.json"
    stats_path = DATA_OUT / "citywide_stats.json"
    with open(tracts_path, "w") as f:
        json.dump(records, f, separators=(",", ":"))
    with open(stats_path, "w") as f:
        json.dump(stats, f, indent=2)

    shutil.copy2(MODEL_PATH, DATA_OUT / MODEL_PATH.name)
    shutil.copy2(MODEL_META_PATH, DATA_OUT / MODEL_META_PATH.name)

    print(f"[write] {tracts_path}  ({len(records):,} tracts, "
          f"{tracts_path.stat().st_size / 1e6:.1f} MB)")
    print(f"[write] {stats_path}  ({len(stats)} numeric columns)")
    print(f"[copy]  {DATA_OUT / MODEL_PATH.name}")
    print(f"[copy]  {DATA_OUT / MODEL_META_PATH.name}")

    # Per-tract quarterly time series (produced by `python -m pipeline.longitudinal`).
    # Additive: when absent the API just 404s the timeseries endpoint, and
    # tracts.json (the latest snapshot) keeps the map/UI working.
    copy_optional(
        TIMESERIES_PATH, DATA_OUT / TIMESERIES_PATH.name,
        missing_hint="no longitudinal time series (run `make timeseries`)",
    )

    build_pmtiles()

    # Council-district outlines for the map overlay (produced by
    # scripts/patch_council_districts.py).
    copy_optional(
        DISTRICTS_OVERLAY_PATH, TILES_OUT / DISTRICTS_OVERLAY_PATH.name,
        missing_hint="no district overlay (run scripts/patch_council_districts.py)",
    )

    print("\nServing bundle ready under serving/.")


if __name__ == "__main__":
    main()
