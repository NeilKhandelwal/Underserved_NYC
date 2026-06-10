"""Join NYC City Council district numbers onto output/master.geojson in place.

Stdlib-only, so council districts can be added to already-computed artifacts
without re-running the full pipeline (the 311 input alone is 13 GB). After
patching, re-run ``python scripts/build_serving_bundle.py`` to propagate the
new ``council_district`` property into serving/data and the vector tiles.

District boundaries: NYC Open Data "City Council Districts" (dataset
872g-cjhh), GeoJSON export:
    https://data.cityofnewyork.us/resource/872g-cjhh.geojson
Save as ``data/nycc.geojson``. The district-number property is ``coundist``
(Open Data) or ``CounDist`` / ``coun_dist`` (DCP exports); all are handled.

Method: each tract's cheap centroid (mean of all coordinates, same as the
serving bundle's fly-to centroid) is tested against district polygons with
even-odd ray casting (handles holes). Centroids that land in no district
(waterfront slivers) fall back to the nearest district centroid and are
reported.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DISTRICTS = PROJECT_ROOT / "data" / "nycc.geojson"
DEFAULT_GEOJSON = PROJECT_ROOT / "output" / "master.geojson"

DISTRICT_KEYS = ("coundist", "CounDist", "coun_dist", "COUNDIST")


def centroid(geometry: dict | None) -> tuple[float, float] | None:
    """Mean of all coordinate pairs (matches build_serving_bundle._centroid)."""
    if not geometry:
        return None
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
        return None
    return sum(xs) / len(xs), sum(ys) / len(ys)


def _rings(geometry: dict) -> list[list[list[float]]]:
    """All rings (outer + holes) of a Polygon/MultiPolygon."""
    coords = geometry.get("coordinates", [])
    if geometry.get("type") == "Polygon":
        return coords
    if geometry.get("type") == "MultiPolygon":
        return [ring for poly in coords for ring in poly]
    return []


def point_in_geometry(lon: float, lat: float, geometry: dict) -> bool:
    """Even-odd ray casting across every ring, so holes toggle correctly."""
    inside = False
    for ring in _rings(geometry):
        j = len(ring) - 1
        for i in range(len(ring)):
            xi, yi = ring[i][0], ring[i][1]
            xj, yj = ring[j][0], ring[j][1]
            if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
                inside = not inside
            j = i
    return inside


def _bbox(geometry: dict) -> tuple[float, float, float, float]:
    xs: list[float] = []
    ys: list[float] = []
    for ring in _rings(geometry):
        for pt in ring:
            xs.append(pt[0])
            ys.append(pt[1])
    return min(xs), min(ys), max(xs), max(ys)


def district_number(props: dict) -> int:
    for key in DISTRICT_KEYS:
        if key in props:
            return int(props[key])
    raise KeyError(f"no district-number property among {DISTRICT_KEYS}: {sorted(props)}")


def load_districts(path: Path) -> list[dict]:
    with open(path) as f:
        gj = json.load(f)
    districts = []
    for feat in gj["features"]:
        geom = feat["geometry"]
        c = centroid(geom)
        districts.append({
            "number": district_number(feat["properties"]),
            "geometry": geom,
            "bbox": _bbox(geom),
            "centroid": c,
        })
    return districts


def assign(lon: float, lat: float, districts: list[dict]) -> tuple[int, bool]:
    """Return (district number, used_fallback)."""
    for d in districts:
        x0, y0, x1, y1 = d["bbox"]
        if x0 <= lon <= x1 and y0 <= lat <= y1 and point_in_geometry(lon, lat, d["geometry"]):
            return d["number"], False
    nearest = min(
        districts,
        key=lambda d: (d["centroid"][0] - lon) ** 2 + (d["centroid"][1] - lat) ** 2,
    )
    return nearest["number"], True


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--districts", type=Path, default=DEFAULT_DISTRICTS)
    ap.add_argument("--geojson", type=Path, default=DEFAULT_GEOJSON)
    args = ap.parse_args()

    for path in (args.districts, args.geojson):
        if not path.exists():
            raise SystemExit(f"Missing input: {path}\n(see module docstring for the download URL)")

    districts = load_districts(args.districts)
    print(f"[read]  {args.districts}  ({len(districts)} districts)")

    with open(args.geojson) as f:
        gj = json.load(f)
    features = gj.get("features", [])

    counts: dict[int, int] = {}
    fallbacks = 0
    skipped = 0
    for feat in features:
        c = centroid(feat.get("geometry"))
        if c is None:
            feat["properties"]["council_district"] = None
            skipped += 1
            continue
        num, fell_back = assign(c[0], c[1], districts)
        feat["properties"]["council_district"] = num
        counts[num] = counts.get(num, 0) + 1
        fallbacks += fell_back

    tmp = args.geojson.with_suffix(".geojson.tmp")
    with open(tmp, "w") as f:
        json.dump(gj, f)
    os.replace(tmp, args.geojson)

    print(f"[write] {args.geojson}  ({len(features):,} tracts)")
    print(f"        nearest-district fallbacks: {fallbacks}, no-geometry: {skipped}")
    print("        tracts per district:")
    for num in sorted(counts):
        print(f"          district {num:>2}: {counts[num]}")


if __name__ == "__main__":
    main()
