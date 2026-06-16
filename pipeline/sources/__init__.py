"""Build-time data-source clients (NYC Open Data / Socrata, US Census ACS).

These replace the multi-GB local CSVs the pipeline used to read from data/.
Each client filters server-side and caches to data/cache/ so multi-quarter and
re-runs are cheap and CI/builds are deterministic.
"""
