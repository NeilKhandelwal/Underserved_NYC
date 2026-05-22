"""Validation suite for the Underservice Risk Index.

Four diagnostic tests:
  - test_temporal_split     — does pre-cutoff risk predict post-cutoff HPD
                              violation rate? (predictive validity)
  - test_bootstrap_ci       — per-tract 90% confidence intervals from
                              resampled input records (precision)
  - test_weight_sensitivity — Kendall τ between base and perturbed
                              composite weights (robustness)
  - test_spatial_residuals  — Moran's I on risk_residual; residuals
                              should NOT cluster spatially (completeness)
"""
