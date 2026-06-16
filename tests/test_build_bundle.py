"""Unit tests for the serving-bundle helpers that don't need the full pipeline
artifacts (master.geojson, the model, tippecanoe)."""
from __future__ import annotations

import json
from pathlib import Path

from scripts.build_serving_bundle import copy_optional


def test_copy_optional_copies_when_present(tmp_path: Path):
    src = tmp_path / "timeseries.json"
    payload = {"36005000100": {"quarters": ["2024Q1"], "risk_score": [42.0]}}
    src.write_text(json.dumps(payload))
    dst = tmp_path / "data" / "timeseries.json"

    copied = copy_optional(src, dst, missing_hint="run `make timeseries`")

    assert copied is True
    assert dst.exists()                          # parent dir auto-created
    assert json.loads(dst.read_text()) == payload


def test_copy_optional_skips_when_absent(tmp_path: Path, capsys):
    src = tmp_path / "missing.json"
    dst = tmp_path / "data" / "missing.json"

    copied = copy_optional(src, dst, missing_hint="run `make timeseries`")

    assert copied is False
    assert not dst.exists()
    assert not dst.parent.exists()               # never touches the bundle on skip
    assert "run `make timeseries`" in capsys.readouterr().out
