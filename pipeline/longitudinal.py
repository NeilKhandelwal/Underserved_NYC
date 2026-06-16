"""Longitudinal quarterly scoring loop (section 2 of docs/longitudinal-design.md).

Runs the EXISTING scoring kernel — ``pipeline.aggregate.aggregate`` +
``pipeline.regression.run_rank_composite`` — once per quarter over API-backed,
date-sliced sources, producing a per-tract quarterly time series. This is the
production version of ``scripts/spike_quarterly.py``: citywide instead of one
borough, all four sources (the spike held vacate empty), and a demographic
residual; it reuses the merged windowed loaders (``load_311(start, end, ...)``
etc.) rather than its own ad-hoc Socrata calls.

Design decisions made concrete here (see the design doc for the rationale):

  - **Demographics (ACS) + building stock (PLUTO) are held constant** across
    quarters: loaded and spatially joined ONCE, then reused for every period.
    The composite ``risk_score`` doesn't use them at all; only the residual does.
    PLUTO is also the slowest join (~860k lots), so doing it once matters.
  - **One fixed demographic model** is trained on a single full-span baseline and
    applied to every quarter (never retrained per quarter). Because the
    demographic inputs are constant per tract, each tract's predicted risk is the
    same every quarter, so ``risk_residual`` trends move only with service change
    (the score), not with model drift — which is the whole point of the residual
    line. Skippable with ``with_residual=False`` (then no sklearn work runs).
  - **Comparability:** ``run_rank_composite`` ranks within whatever frame it's
    given (``.rank(pct=True)``), so a quarter's ``risk_score`` is a tract's
    *relative* rank that quarter. The raw composite components are also stored —
    those ARE absolute-comparable across quarters — so the UI can show both.
  - **Rolling windows:** quarterly per-tract counts are small/noisy; pass
    ``rolling=N`` to score each label over the N quarters ending at it instead of
    the single discrete quarter.

Output: ``output/timeseries.json`` (the bundle step copies it into
``serving/data/`` if present — that wiring is a later PR), schema::

    { "<GEOID>": { "quarters": ["2024Q1", ...],
                   "risk_score": [..], "risk_residual": [..],
                   "accountability_gap": [..], "weighted_violation_rate": [..],
                   "avg_closure_time_adjusted": [..], "vacate_rate": [..] } }

Per-metric arrays are aligned to ``quarters`` and null-padded where a tract had
no score that quarter, so the frontend sparkline gets a consistent x-axis.

Run:
    python -m pipeline.longitudinal                       # 2024 Q1-Q4, citywide
    python -m pipeline.longitudinal --quarters 2024Q1 2024Q2 2024Q3
    python -m pipeline.longitudinal --rolling 4           # rolling 4Q windows
    python -m pipeline.longitudinal --borough BRONX --no-residual   # quick check
    SOCRATA_APP_TOKEN=xxxx python -m pipeline.longitudinal           # higher rate limit
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
from pathlib import Path

import pandas as pd

from pipeline.load_and_clean import (
    PROJECT_ROOT, load_311, load_acs, load_hpd, load_pluto, load_tracts,
    load_vacate_orders,
)
from pipeline.aggregate import aggregate
from pipeline.regression import run_rank_composite
from pipeline.spatial_join import (
    join_311_to_tracts, join_hpd_to_tracts, join_pluto_to_tracts,
    join_vacate_to_tracts,
)

DEFAULT_OUT = PROJECT_ROOT / "output" / "timeseries.json"

# The raw composite inputs (see pipeline/regression.COMPOSITE_WEIGHTS). Stored
# alongside risk_score because, unlike the within-period percentile score, these
# are absolute-comparable across quarters.
COMPONENT_COLS = [
    "accountability_gap",
    "weighted_violation_rate",
    "avg_closure_time_adjusted",
    "vacate_rate",
]


@contextlib.contextmanager
def _quiet(verbose: bool):
    """Silence the chatty pipeline internals (per-join counts, aggregate's
    describe()) unless --verbose; they'd otherwise dwarf the per-quarter lines."""
    if verbose:
        yield
    else:
        with contextlib.redirect_stdout(io.StringIO()), \
             contextlib.redirect_stderr(io.StringIO()):
            yield


# ── Quarter math ─────────────────────────────────────────────────────────────

def parse_quarter(label: str) -> tuple[int, int]:
    """'2024Q3' -> (2024, 3). Raises ValueError on a malformed label."""
    year, sep, q = label.partition("Q")
    if sep != "Q" or not q.isdigit() or not (1 <= int(q) <= 4):
        raise ValueError(f"bad quarter label {label!r} (expected e.g. '2024Q3')")
    return int(year), int(q)


def _quarter_index(label: str) -> int:
    """Absolute quarter ordinal so consecutive quarters differ by 1."""
    year, q = parse_quarter(label)
    return year * 4 + (q - 1)


def _label_from_index(idx: int) -> str:
    year, q = divmod(idx, 4)
    return f"{year}Q{q + 1}"


def quarter_bounds(label: str) -> tuple[str, str]:
    """Half-open [start, end) ISO dates for a single quarter."""
    year, q = parse_quarter(label)
    start = f"{year}-{3 * (q - 1) + 1:02d}-01"
    end = f"{year + 1}-01-01" if q == 4 else f"{year}-{3 * q + 1:02d}-01"
    return start, end


def rolling_bounds(label: str, window: int) -> tuple[str, str]:
    """[start, end) spanning the `window` quarters ending at (and including)
    `label` — e.g. rolling_bounds('2024Q4', 4) covers all of 2024."""
    if window < 1:
        raise ValueError("rolling window must be >= 1")
    start = quarter_bounds(_label_from_index(_quarter_index(label) - (window - 1)))[0]
    return start, quarter_bounds(label)[1]


def quarters_between(start_label: str, end_label: str) -> list[str]:
    """Inclusive list of quarter labels from start to end, e.g.
    ('2024Q1', '2025Q1') -> 5 labels. Convenience for callers/tests."""
    lo, hi = _quarter_index(start_label), _quarter_index(end_label)
    if hi < lo:
        raise ValueError(f"{end_label} precedes {start_label}")
    return [_label_from_index(i) for i in range(lo, hi + 1)]


# ── Per-period scoring (the unchanged kernel) ────────────────────────────────

def score_period(tracts, acs, joined_pluto, start: str, end: str, *,
                 borough: str | None = None, verbose: bool = False) -> pd.DataFrame:
    """Load + join + aggregate + composite-score one [start, end) window.

    Returns the aggregate() frame with a ``risk_score`` column, restricted to
    tracts that actually scored. ACS and the already-joined PLUTO are passed in
    so they're computed once and held constant across all calls."""
    with _quiet(verbose):
        joined_311 = join_311_to_tracts(load_311(start, end, borough=borough), tracts)
        joined_hpd = join_hpd_to_tracts(load_hpd(start, end, borough=borough), tracts)
        joined_vacate = join_vacate_to_tracts(load_vacate_orders(start, end), tracts)
        tract_df = aggregate(
            tracts, joined_311, joined_hpd, joined_vacate, acs, joined_pluto
        ).reset_index(drop=True)
        scores, _ = run_rank_composite(tract_df)
        tract_df.loc[scores.index, "risk_score"] = scores
    return tract_df.dropna(subset=["risk_score"])


def _baseline_predictions(tracts, acs, joined_pluto, periods, *,
                          borough: str | None, verbose: bool) -> dict[str, float]:
    """Train ONE demographic model over the full span the quarters cover and
    return {GEOID: predicted_risk}. Held fixed across quarters by construction —
    so the per-quarter residual reflects service change, not model drift.

    Uses cross_val_predict (out-of-fold), matching pipeline.demographic_analysis,
    so the baseline predictions aren't in-sample-optimistic."""
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.model_selection import cross_val_predict

    from pipeline.demographic_analysis import DEMOGRAPHIC_FEATURES

    span_start = min(p[1] for p in periods)
    span_end = max(p[2] for p in periods)
    base = score_period(tracts, acs, joined_pluto, span_start, span_end,
                        borough=borough, verbose=verbose)

    feats = [c for c in DEMOGRAPHIC_FEATURES if c in base.columns]
    if not feats:
        raise RuntimeError(
            "No DEMOGRAPHIC_FEATURES found in baseline columns; "
            f"available: {list(base.columns)}"
        )
    data = base[["GEOID", "risk_score"] + feats].dropna()
    model = RandomForestRegressor(
        n_estimators=300, min_samples_leaf=3, random_state=42, n_jobs=-1
    )
    preds = cross_val_predict(
        model, data[feats].values, data["risk_score"].values, cv=5, n_jobs=-1
    )
    print(f"  baseline model: {len(data):,} tracts over [{span_start}..{span_end}), "
          f"{len(feats)} demographic features (held fixed across quarters)")
    return dict(zip(data["GEOID"].astype(str), (round(float(p), 4) for p in preds)))


# ── Assembly ─────────────────────────────────────────────────────────────────

def _assemble(quarter_labels: list[str], scored: dict[str, pd.DataFrame],
              predicted: dict[str, float], with_residual: bool) -> dict[str, dict]:
    """Pivot per-quarter scored frames into the GEOID-keyed time-series schema.

    Every metric array is aligned to `quarter_labels` and null-padded where the
    tract had no score that quarter. Tracts scored in zero quarters are omitted.

    aggregate() yields one row per tract, so GEOID is expected unique within a
    quarter. We check that explicitly and fail loudly on a duplicate (an upstream
    contract break) rather than letting df.loc[g] later return a DataFrame and
    raise a cryptic TypeError in the float() conversion."""
    by_q: dict[str, pd.DataFrame] = {}
    for q, df in scored.items():
        indexed = df.assign(GEOID=df["GEOID"].astype(str)).set_index("GEOID")
        if not indexed.index.is_unique:
            dupes = indexed.index[indexed.index.duplicated()].unique().tolist()
            raise ValueError(
                f"{q}: duplicate GEOID rows in scored frame {dupes[:5]} — "
                "aggregate() is expected to yield one row per tract"
            )
        by_q[q] = indexed
    geoids = sorted({g for df in by_q.values() for g in df.index})

    def cell(row, col: str, ndigits: int):
        val = row.get(col)
        return None if val is None or pd.isna(val) else round(float(val), ndigits)

    series: dict[str, dict] = {}
    for g in geoids:
        risk, resid = [], []
        comps: dict[str, list] = {c: [] for c in COMPONENT_COLS}
        for q in quarter_labels:
            df = by_q[q]
            if g in df.index:
                row = df.loc[g]
                score = round(float(row["risk_score"]), 2)
                risk.append(score)
                for c in COMPONENT_COLS:
                    comps[c].append(cell(row, c, 4))
                pred = predicted.get(g)
                resid.append(None if pred is None else round(score - pred, 2))
            else:
                risk.append(None)
                for c in COMPONENT_COLS:
                    comps[c].append(None)
                resid.append(None)
        entry: dict[str, object] = {"quarters": quarter_labels, "risk_score": risk}
        if with_residual:
            entry["risk_residual"] = resid
        entry.update(comps)
        series[g] = entry
    return series


def build_timeseries(quarter_labels: list[str], *, rolling: int | None = None,
                     with_residual: bool = True, borough: str | None = None,
                     verbose: bool = False) -> dict[str, dict]:
    """Score every quarter and return the GEOID-keyed time series.

    `rolling=N` scores each label over the N quarters ending at it (noise
    smoothing); otherwise each label is its own discrete quarter.
    """
    with _quiet(verbose):
        tracts = load_tracts()
        acs = load_acs()
        joined_pluto = join_pluto_to_tracts(load_pluto(), tracts)

    if rolling:
        periods = [(q, *rolling_bounds(q, rolling)) for q in quarter_labels]
        print(f"Scoring {len(periods)} rolling {rolling}Q windows"
              f"{f' (borough={borough})' if borough else ' (citywide)'}:")
    else:
        periods = [(q, *quarter_bounds(q)) for q in quarter_labels]
        print(f"Scoring {len(periods)} quarters"
              f"{f' (borough={borough})' if borough else ' (citywide)'}:")

    scored: dict[str, pd.DataFrame] = {}
    for label, start, end in periods:
        df = score_period(tracts, acs, joined_pluto, start, end,
                          borough=borough, verbose=verbose)
        scored[label] = df
        print(f"  {label} [{start}..{end}): {len(df):,} tracts scored")

    predicted: dict[str, float] = {}
    if with_residual:
        predicted = _baseline_predictions(
            tracts, acs, joined_pluto, periods, borough=borough, verbose=verbose
        )

    return _assemble(quarter_labels, scored, predicted, with_residual)


def write_timeseries(series: dict[str, dict], out: Path = DEFAULT_OUT) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        json.dump(series, f, separators=(",", ":"))
    print(f"\nWrote {out}  ({len(series):,} tracts, "
          f"{out.stat().st_size / 1e6:.2f} MB)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--quarters", nargs="+", default=quarters_between("2024Q1", "2024Q4"),
                    help="explicit quarter labels, e.g. 2024Q1 2024Q2 (default: 2024 Q1-Q4)")
    ap.add_argument("--rolling", type=int, metavar="N",
                    help="score each label over the trailing N quarters (noise smoothing)")
    ap.add_argument("--borough", help="limit 311/HPD to one borough (uppercase) — quick test")
    ap.add_argument("--no-residual", dest="residual", action="store_false",
                    help="skip the demographic residual (no sklearn; faster)")
    ap.add_argument("--verbose", action="store_true", help="show pipeline-internal logs")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    series = build_timeseries(
        args.quarters, rolling=args.rolling, with_residual=args.residual,
        borough=args.borough, verbose=args.verbose,
    )
    write_timeseries(series, args.out)

    # Illustrate the trend on a few tracts present in every requested quarter.
    complete = {
        g: v["risk_score"] for g, v in series.items()
        if all(s is not None for s in v["risk_score"])
    }
    print(f"\nExample trends ({len(complete):,} tracts scored in all "
          f"{len(args.quarters)} periods):")
    print(f"  {'GEOID':<12} " + "  ".join(f"{q:>7}" for q in args.quarters) + "   Δ")
    for g in list(complete)[:6]:
        vals = complete[g]
        delta = vals[-1] - vals[0]
        arrow = "↑" if delta > 1 else "↓" if delta < -1 else "→"
        print(f"  {g:<12} " + "  ".join(f"{v:7.1f}" for v in vals)
              + f"   {arrow} {delta:+.1f}")


if __name__ == "__main__":
    main()
