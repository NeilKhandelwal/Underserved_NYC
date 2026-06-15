"""Run the full validation suite.

Usage:
    python -m validation.run_all                 # full suite
    python -m validation.run_all --fast          # skip bootstrap (slowest)
    python -m validation.run_all --only weights  # run one test

Tests are ordered cheapest → most expensive so quick signals surface first.
"""
import argparse
import json

from validation.test_spatial_residuals import run as test_spatial
from validation.test_temporal_split import run as test_temporal
from validation.test_temporal_split_leave_one_out import run as test_temporal_loo
from validation.test_weight_sensitivity import run as test_weights
from validation.test_bootstrap_ci import run as test_bootstrap

TESTS = [
    ("weights",       test_weights,      "fast"),
    ("spatial",       test_spatial,      "fast"),
    ("temporal",      test_temporal,     "medium"),
    ("temporal_loo",  test_temporal_loo, "medium"),
    ("bootstrap",     test_bootstrap,    "slow"),
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fast", action="store_true",
                        help="skip the slowest test (bootstrap CIs)")
    parser.add_argument("--only", choices=[t[0] for t in TESTS],
                        help="run only the named test")
    parser.add_argument("--n-boot", type=int, default=200,
                        help="bootstrap iterations (test 3)")
    parser.add_argument("--cutoff", type=str, default="2024-10-01",
                        help="temporal split cutoff date (test 2)")
    args = parser.parse_args()

    results: dict = {}
    for name, fn, speed in TESTS:
        if args.only and name != args.only:
            continue
        if args.fast and speed == "slow":
            print(f"\n[SKIP] {name} (--fast)")
            continue
        try:
            if name == "bootstrap":
                results[name] = fn(n_boot=args.n_boot)
            elif name in ("temporal", "temporal_loo"):
                results[name] = fn(cutoff_date=args.cutoff)
            else:
                results[name] = fn()
        except Exception as e:
            print(f"\n[ERROR] {name} raised: {e.__class__.__name__}: {e}")
            results[name] = {"error": str(e)}

    print("\n" + "=" * 60)
    print("  Validation Suite Summary")
    print("=" * 60)
    print(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()
