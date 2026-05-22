"""Shared helpers for the validation suite."""
import contextlib
import io
from pathlib import Path

import geopandas as gpd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
OUTPUT_DIR = PROJECT_ROOT / "output"


def load_master_geojson() -> gpd.GeoDataFrame:
    path = OUTPUT_DIR / "master.geojson"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Run `python -m pipeline.score` first."
        )
    return gpd.read_file(path)


@contextlib.contextmanager
def silence_stdout():
    """Suppress print() output from pipeline internals (e.g. in tight loops)."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        yield


def print_header(title: str) -> None:
    bar = "─" * max(len(title) + 4, 60)
    print(f"\n{bar}\n  {title}\n{bar}")


def verdict(ok: bool, ok_msg: str = "PASS", fail_msg: str = "WARN") -> str:
    return f"[{ok_msg}]" if ok else f"[{fail_msg}]"
