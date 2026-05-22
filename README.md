# NYC Underservice Risk Index

A data pipeline and interactive web app that quantifies **municipal neglect** across every NYC census tract, then disentangles how much of that neglect is explained by demographics — and how much isn't.

The headline finding is not the risk score itself ("poor neighborhoods get worse service" surprises no one). It's the **residual**: tracts where actual neglect *exceeds* what poverty, race, rent burden, and education alone predict. That gap is what the index is designed to surface.

---

## Motivation

Most "neglect" maps are really just poverty maps with extra steps. If you map any housing-stress signal in NYC — 311 closure times, HPD violations, vacate orders — you'll get back a near-clone of the income map. The interesting question is therefore not *where* neglect happens but *where it happens that you wouldn't predict from socioeconomics alone*.

Underservice has two separable components:

1. **Structural** — low-income, majority-minority neighborhoods receive worse city services citywide. This is the background pattern, real but not surprising, and not fully attributable to municipal choice.
2. **Institutional** — specific tracts receive worse service than even the structural pattern predicts. This gap is what the index is designed to surface. It is more likely to reflect agency routing decisions, inspection coverage, landlord enforcement patterns, and political responsiveness than the demographic composition of the neighborhood.

This project tackles that decomposition in three layers:

1. Build a defensible **risk score** from independent housing-stress signals.
2. Establish a **baseline** — how much of risk score variance is explained by ACS demographics *and* building stock (PLUTO)? The baseline intentionally includes both so the residual reflects city-discretionary behavior, not structural housing conditions.
3. Compute the **residual** — actual risk minus baseline prediction. Positive residual = neglect that can't be attributed to who lives there or what was built there.

---

## Data Sources

| Source | Used For | Notes |
|---|---|---|
| NYC 311 Service Requests (2024–present) | Closure-time signal, complaint rates | Filtered to 19 housing complaint types only; auto-closes (<1 hr, "no action" resolutions) removed |
| HPD Class C Violations | Severity signal — most serious housing code violations | Filtered by class field, lat/lon required |
| HPD Order to Repair / Vacate Orders | Severity weighting — buildings declared uninhabitable | Aggregated by `vacated_units` per tract |
| ACS 2022 5-Year Estimates (Census API) | Demographics + denominators | 14 variables; ratios computed (poverty rate, rent burden, etc.) |
| NYC 2020 Census Tract Boundaries (`nyct2020.shp`) | Spatial unit of analysis | Reprojected from EPSG:2263 → EPSG:4326 |
| NYC PLUTO (`pluto.csv`) | Building-stock features | Residential lots only; yields `median_year_built`, `pct_prewar_units`, `pct_rent_stab_proxy` per tract |

Volume after filtering: ~1.78M 311 records, ~2.50M HPD violations, ~8.5K vacate orders, ~700K PLUTO residential lots, ~2,172 tracts with complete data.

---

## Pipeline Architecture

```
data/                    raw inputs (shapefile, 3 CSVs)
pipeline/
├── load_and_clean.py    Stage 1 — read, filter, reproject, fetch ACS
├── spatial_join.py      Stage 2 — assign GEOID to each point record
├── aggregate.py         Stage 3 — collapse to one row per tract + derived rates
├── regression.py        Stage 4 — rank composite scoring (was OLS, abandoned)
├── score.py             Stage 5 — orchestrator + GeoJSON export
└── demographic_analysis.py  Stage 6 — correlation, RF training, residuals
output/
├── master.geojson       2,197 scored tracts with all features + residuals
├── demographic_model.joblib   trained Random Forest
└── demographic_model.json     R², RMSE, feature importance, slider ranges
app.py                   Streamlit + Folium UI
```

### Stage 1 — `load_and_clean.py`

Each loader **sniffs original CSV column names** before normalization, so it survives NYC OpenData renaming columns (e.g. "Complaint Type" → "Problem (formerly Complaint Type)"). All point data is filtered to a coarse NYC bounding box and converted to EPSG:4326 GeoDataFrames.

ACS pull uses one Census API call for 14 variables across NY counties 005/047/061/081/085 (the five boroughs) and computes derived rates with a `safe_ratio()` helper that returns NaN when the denominator is 0 or null.

### Stage 2 — `spatial_join.py`

`gpd.sjoin(points, tracts, how="inner", predicate="within")` assigns each 311 / HPD / vacate record a `GEOID`. Inner join drops anything that falls outside an NYC tract (parks, rivers, geocoding errors).

### Stage 3 — `aggregate.py`

Per tract, computes:

| Column | Formula |
|---|---|
| `avg_closure_time` | mean of `closure_time_days` over 311 records |
| `complaint_rate` | 311 count / population |
| `violation_rate` | HPD count / housing_units |
| `vacate_rate` | vacated units / housing_units |
| `weighted_violation_rate` | `violation_rate × (1 + vacate_rate)` — severity amplification |
| `accountability_gap` | `weighted_violation_rate / (complaint_rate + 0.001)` |
| `median_year_built` | median construction year of residential PLUTO lots in tract |
| `pct_prewar_units` | share of residential units in buildings built before 1947 |
| `pct_rent_stab_proxy` | share of residential units in pre-1974 buildings with ≥6 units (ETPA stabilization proxy) |

Drops tracts with zero population, zero housing units, or any null in core ACS fields. Census's `-666666666` null sentinel is replaced with NaN before any arithmetic.

### Stage 4 — `regression.py` (rank composite)

The original plan was OLS regression with `avg_closure_time` as the target. It was abandoned: R² = 0.029, and several coefficients had unexpected signs. Closure time variance is dominated by factors we don't observe (complaint type, season, building owner, agency triage policy), so OLS was overfitting noise.

Replaced with a **rank composite**:

```python
COMPOSITE_WEIGHTS = {
    "accountability_gap":      0.40,
    "weighted_violation_rate": 0.30,
    "avg_closure_time":        0.20,
    "vacate_rate":             0.10,
}
ranks = features.rank(pct=True)            # each feature → percentile [0,1]
weighted = Σ ranks[f] * weight[f]
score = (weighted / Σ weights) * 100       # → 0–100
```

Why rank composite over a regression?
- **Interpretable units** — score 80 means top 20% on most dimensions, not "0.7 std above mean."
- **Robust to scale and outliers** — one runaway tract doesn't blow up the score for everyone.
- **No target leakage** — the score doesn't predict closure time *from* closure time.
- **Weights are conceptual, not fitted** — accountability_gap weighted highest because "violations exist but no one's complaining" is the most direct signal of neglect.

Final score distribution (n=2,197): mean 50.0, std 20.7, range 1.2–92.8 — full spread, not clipped.

### Stage 5 — `score.py`

Orchestrates Stages 1–4 and writes `output/master.geojson`. Display columns include score, all raw features, and demographic ratios. CRS forced to EPSG:4326 with `allow_override=True` since the Choropleth library expects WGS84.

### Stage 6 — `demographic_analysis.py`

Three things:

1. **Correlation report** — Pearson r between each demographic and `risk_score`, sorted by |r|.
2. **Random Forest training** — `RandomForestRegressor(n_estimators=300, min_samples_leaf=3)`, 80/20 train/test split, reports R², RMSE, and feature importance. Saves `demographic_model.joblib` plus a metadata JSON containing slider ranges (min/median/max per feature) for the UI.
3. **Residual export** — `cross_val_predict(cv=5)` produces honest out-of-sample predictions for *all* tracts, then `risk_residual = risk_score - predicted_risk` is merged back into `master.geojson`.

Latest results (current data):

```
R²:   0.748
RMSE: 10.37   (on 0–100 scale)

Pearson r vs risk_score (sorted by |r|):
  median_income        -0.579
  poverty_rate         +0.535
  pct_hispanic         +0.434
  pct_bachelors        -0.389
  pct_prewar_units     +0.340
  unemployment_rate    +0.314
  pct_black            +0.302
  rent_burden          +0.298
  median_year_built    -0.236
  pct_rent_stab_proxy  +0.218
  pct_foreign_born     +0.161
  mean_commute_time    +0.102

RF feature importance:
  median_income        0.454
  pct_prewar_units     0.128   ← building stock is the #2 predictor
  pct_black            0.087
  poverty_rate         0.069
  median_year_built    0.063
  pct_rent_stab_proxy  0.047
  pct_hispanic         0.033
  pct_bachelors        0.030
  rent_burden          0.028
  mean_commute_time    0.022
  pct_foreign_born     0.019
  unemployment_rate    0.018
```

**Interpretation:** the model explains ~75% of risk variance from non-discretionary features. Building stock (PLUTO) accounts for ~21% of that importance — pre-war unit share alone is the second most important feature after income. The remaining ~25% is the residual this project surfaces.

**Spatial validation (Moran's I on residuals):** after controlling for all 12 features, residuals still carry a Moran's I of +0.194 (z = 16.7, p < 0.001). This is a finding, not a defect. Service quality has institutional geography — HPD inspection routing, community board responsiveness, council district capacity — that no tract-level feature can capture. The spatial clustering in residuals is evidence that *something institutional* explains the remainder.

---

## App (`app.py`)

Streamlit + Folium. The map fills the main content area. Two CSS-positioned floating cards sit on top of it:

- **Filter card (top-left)** — always visible; holds the overlay layer radio and its caption. Hovers over the map with a blur backdrop, no separate sidebar.
- **Detail card (top-right)** — only appears when a tract is clicked; contains the neighborhood metrics panel with a ✕ close button. Dismisses via the close button or by clicking another tract.

Both cards use Streamlit's `st.container(key=...)` API, which emits `class="st-key-<key>"` on the container div, which is then absolutely positioned via a CSS rule in `app.py`'s `<style>` block. The native Streamlit sidebar is hidden with `display: none`.

**Auto-pan + highlight:** When a tract is clicked, the map re-renders with `location = (tract_centroid_lat, tract_centroid_lon − 0.010)` and `zoom_start = 14`. The ~1km west offset ensures the selected tract falls to the left of the right-side detail card. The selected tract is also outlined with a dashed white border (weight 4) via a second `folium.GeoJson` layer, so it's visually obvious which tract the detail card refers to. The `st_folium` key includes the active GEOID so the map widget is forced to rebuild on selection change.

**Draggable cards:** Both floating cards can be repositioned by click-dragging on any non-interactive area. Implementation is a 0-height `streamlit.components.v1.html` iframe that reaches into `window.parent.document` to attach `mousedown` / `mousemove` / `mouseup` handlers to elements with the floating-card classes. Mousedown on an input / button / label / radio / slider is ignored so normal widget interaction still works. A `MutationObserver` re-attaches after Streamlit reruns (which replace the card DOM nodes), and a flag on `window.parent` prevents multiple observers from stacking.

**Click deduplication:** `st_folium` returns `last_clicked` with persistent coordinates across every rerun, which previously made the detail panel "stick" on the old tract whenever any other widget was touched (and also caused the "double-click-in-watchlist" sticky bug). The app now tracks the last click key in `st.session_state` and only processes *new* coordinate values.

### Map overlays (sidebar radio)

| Layer | Column | Color logic |
|---|---|---|
| Risk Score | `risk_score` | RdYlGn_r (red = high risk) |
| **Unexplained Neglect (Residual)** | `risk_residual` | RdYlGn_r (red = neglect exceeds prediction) |
| Predicted Risk (from demographics) | `predicted_risk` | RdYlGn_r |
| Median Income | `median_income` | RdYlGn (inverted — green = higher income) |
| Poverty Rate | `poverty_rate` | RdYlGn_r |
| % Black, % Hispanic, % Foreign-Born | respective | RdYlGn_r |
| Rent Burden, Unemployment | respective | RdYlGn_r |
| % Bachelor's+ | `pct_bachelors` | RdYlGn (inverted) |

Color scales are inverted for *protective* demographics (income, education) so green always = "less concerning."

The **Unexplained Neglect** (residual) layer uses **fixed symmetric bins** — `[−edge, −20, −10, 0, 10, 20, +edge]` — not quantile binning. Rationale: the RF's RMSE is ~15 points, so residuals inside ±10 are within the noise floor and shouldn't be distinguishable by color. Fixed bins make magnitude visible; a tract at +3 looks muted (as it should), a tract at +25 pops (as it should). Quantile binning would paint the top 16% red regardless of magnitude, which visually overstates small residuals.

### Detail panel
Click any tract → header (neighborhood / borough / GEOID), large risk score in color-coded threshold (≥75 red, ≥50 amber, else teal), then metric boxes for each indicator with a `Nx higher/lower than city avg` comparison.

### Below the map
- **Top Residual Outliers** — ranked table of tracts whose risk score diverges most from what demographics predict. Toggleable direction (most unexplained neglect / unexpected success / biggest absolute surprise), borough filter, and row-count slider. This is the watchlist view — the tracts worth investigating first.
- **Demographics vs. Risk Score** — bar chart + table of Pearson correlations.
- **Predict Risk Score from Demographics** — sliders for each feature (bounded by min/max from training data, default to median), live RF prediction with the same color thresholds. Feature importance bar chart underneath.
- **Methodology expander** — full writeup of formulas, weights, known biases, data sources.

---

## Mathematical Details

### Severity-weighted violation rate

Vacate orders are HPD's nuclear option — buildings declared uninhabitable. Treating a tract with 100 minor violations the same as one with 100 violations + 5 vacated buildings is wrong. The amplification:

```
weighted_violation_rate = violation_rate × (1 + vacate_rate)
```

A tract with 0 vacate orders gets multiplier 1 (no amplification). A tract with 1% of units vacated gets multiplier 1.01 — noticeable but bounded.

### Accountability gap

```
accountability_gap = weighted_violation_rate / (complaint_rate + 0.001)
```

The +0.001 prevents division by zero. High accountability gap = "violations exist but residents aren't filing 311s." This is the strongest single neglect signal because it's not contaminated by agency response time.

### Percentile rank vs. z-score vs. min-max

| Method | Formula | Outlier sensitivity | Interpretability |
|---|---|---|---|
| Z-score | `(x - μ) / σ` | High — one outlier shifts μ and σ | "Std deviations from mean" |
| Min-max | `(x - min) / (max - min)` | Very high — one outlier compresses everyone | "Fraction of range" |
| **Percentile rank** | `rank(x) / N` | Low — order is preserved, magnitudes don't matter | "Top X% on this dimension" |

Picked rank because the input distributions are skewed (some tracts have 50× more violations than the median — z-scores get pathological).

### Closure-time double correction

Raw `avg_closure_time` per tract is unfit for the composite — it conflates *what* gets complained about with *how* the agency responds, and is biased downward in heavily-triaged tracts. Two cascaded corrections produce `avg_closure_time_adjusted`, which is what the composite actually consumes (20% weight).

**Fix 1 — per-complaint-type normalization (multiplicative, against a category baseline).**
Heat complaints close in days; mold complaints take months. A tract heavy on heat looks "fast" by accident. For each 311 record we divide:

```
closure_ratio_record = closure_time_days / citywide_median(complaint_type)
```

Then average per tract → `avg_closure_ratio`. This is unitless: 1.0 = exactly typical for that tract's complaint mix; 1.5 = 50% slower than typical.

**Fix 2 — triage residualization (additive, against a regression line).**
HPD prioritizes high-violation tracts, so they get artificially fast closure. Without correction, `avg_closure_ratio` understates neglect in those tracts. Fit OLS:

```
avg_closure_ratio = a + b · violation_rate          (across all tracts)
```

Then for each tract:

```
avg_closure_time_adjusted = (avg_closure_ratio − predicted) + citywide_mean(avg_closure_ratio)
```

Result interpretation: at the citywide mean = exactly as fast as triage predicts; above = slower than triage explains (real unresponsiveness); below = faster than triage explains (genuinely responsive).

The cascade in pseudocode:

```
record-level closure_time
  ÷ citywide median per complaint type    ← Fix 1 (ratio)
  → tract-level mean (avg_closure_ratio)
  − OLS prediction from violation_rate     ← Fix 2 (residual)
  + citywide mean (recenter)
  = avg_closure_time_adjusted              ← used in composite (20%)
```

Raw `avg_closure_time` (in days) is retained on the GeoJSON for display in the click panel, since the unitless adjusted value is harder for users to read.

### Residual computation

```python
preds = cross_val_predict(rf, X, y, cv=5)   # honest out-of-sample
residual = y - preds                          # actual − predicted
```

5-fold CV ensures no tract's residual was computed by a model that saw it during training. A residual of +20 means "this tract is 20 points more underserved than its demographics would predict" (interpretable on the same 0–100 scale as the score).

---

## Robustness Check — Bias-Correction Sensitivity

The two OLS residualizations in Stage 3 (1c income adjustment, 1d triage adjustment) are *opinionated*: they assume `log(median_income)` and `violation_rate` are confounders to be removed, not mediators on the same causal pathway. [`validation/test_correction_sensitivity.py`](validation/test_correction_sensitivity.py) tests how much the index actually depends on those modeling choices by recomputing the composite with each correction disabled and comparing to production.

| Variant | Spearman ρ | Top-20 overlap | Mean \|Δrank\| |
|---|---|---|---|
| 1c off (no income correction) | 0.931 | 80% | 153 |
| **1d off (no triage correction)** | **0.995** | **45%** | **47** |
| Both off (raw composite) | 0.920 | 50% | 176 |

**The corrections are doing real work — they're not inert.**

The most informative row is **1d off**. Overall ρ is 0.995 — almost identical ordering across all 2,197 tracts — but top-20 overlap collapses to 45%. Triage residualization barely touches the bulk of the distribution but heavily reshuffles *which tracts get flagged as worst*. That matches the design intent: high-violation tracts get artificially fast service, so removing that bias promotes tracts that look "merely bad" into the top.

**Direction of the corrections is sensible.**

| Corrections LIFT (more underserved in production than raw) | Corrections SUPPRESS (less underserved in production than raw) |
|---|---|
| Mott Haven–Port Morris, Bronx | Carroll Gardens–Cobble Hill, Brooklyn |
| Co-op City, Bronx | Park Slope, Brooklyn |
| East Flatbush–Farragut, Brooklyn | Fort Greene, Brooklyn |
| Coney Island–Sea Gate, Brooklyn | Canarsie, Brooklyn |
| Spring Creek–Starrett City, Brooklyn | Breezy Point–Belle Harbor, Queens |
| East Williamsburg, Brooklyn | South Ozone Park, Queens |

The lifted set is dominated by outer-borough lower-income tracts (where 311 under-reporting and triage prioritization both bias the raw composite *downward*). The suppressed set is dominated by gentrified Brooklyn (where high 311 filing rates inflate the raw composite *upward*). That's exactly the bias the corrections are designed to remove, applied in the expected direction.

---

## Known Limitations

1. **Wealthier areas file 311s at different rates.** *(corrected in `aggregate.py`)* `complaint_rate` is residualized against `log(median_income)` via OLS and re-centered on the citywide mean. `accountability_gap` uses this adjusted rate, so gentrification-driven over- (or under-) reporting no longer biases the score. Raw `complaint_rate` is retained on the GeoJSON for comparison.
2. **HPD response prioritization may make high-violation tracts look "fast."** *(corrected in `aggregate.py` — Fix 2 below.)* Triage endogeneity is removed by residualizing the type-adjusted closure ratio against `violation_rate` via OLS and recentering on the citywide mean.
3. **311 has duplicate complaints from the same building.** No deduplication by BBL — a single bad landlord generating 50 complaints inflates one tract's complaint_rate.
4. **Closure-time variance is dominated by complaint type.** *(corrected in `aggregate.py` — Fix 1 below.)* Each 311 record's `closure_time_days` is divided by the citywide median for its complaint type before tract-level aggregation, yielding a unitless per-tract responsiveness ratio that no longer mixes substance with category.
5. **Residual interpretation is descriptive, not causal.** A high residual identifies *unexplained* variance, not a *cause* of neglect. The cause could be landlord behavior, agency policy, council district capacity, or unmeasured demographics.
6. **Static snapshot.** Risk score is a single point-in-time aggregate over 2024–present; no trend analysis.
7. **Tract-level small-sample noise.** Small tracts (fewer 311s/violations) have noisier rates. No confidence intervals or sample-size filtering beyond the population/housing-units gates.

---

## Stack

```
geopandas         spatial joins, GeoJSON IO
pandas            tabular ops
shapely           point-in-polygon for click handling
scikit-learn      RandomForestRegressor + cross_val_predict
joblib            model persistence
streamlit         web UI
folium            choropleth + interactive map
streamlit-folium  bridge for click events
requests          Census API
```

Census tract shapefile reprojected once at load (EPSG:2263 → 4326). Chunked CSV reading (`chunksize=50_000`) for the 4M+ row 311 file to keep memory bounded.

---

## Reproducing

```bash
# 1. Drop raw data into data/
data/nyct2020.{shp,dbf,prj,shx}
data/311_data.csv
data/hpd_violations.csv
data/Order_To_Repair.csv
data/pluto.csv          # or pluto_24v3.csv etc — loader auto-detects

# 2. Build the scored GeoJSON (~5–15 min depending on machine)
python -m pipeline.score

# 3. Train the demographic RF + residuals
python -m pipeline.demographic_analysis

# 4. Launch
streamlit run app.py
```

Re-run step 2 only if the underlying CSVs change. Step 3 only depends on `master.geojson` and rewrites residuals into it in place.

---

## Future Ideation

### Near-term (improves credibility of current claims)

1. **External validation against ground truth.**
   Cross-reference the top-50 highest-residual tracts against:
   - Housing court filings (NYC OCA dataset)
   - Local news coverage of specific buildings
   - Council member oversight reports / public statements
   - Tenant organizing campaigns (Right to Counsel, Met Council on Housing)

   If the model flags places that already have organized tenant pushback, that's converging evidence. Could be done as a manual qualitative validation in a notebook.

2. **Sample-size confidence.**
   For each tract, report a stability indicator (e.g. number of 311s, 95% CI on closure time via bootstrap). Flag low-N tracts in the UI so users don't over-interpret a noisy estimate.

3. **Building-level deduplication.**
   Join 311 records to BBL/BIN, deduplicate complaints from the same building within 7 days. This addresses the "one bad landlord = 50 complaints" inflation.

### Medium-term (new capabilities)

6. **Time trend panel.**
   Compute risk scores quarterly. Show per-tract trajectory: improving, worsening, stable. Surface the 10 fastest-deteriorating tracts as a watchlist.

7. **Actionable drill-down per tract.**
   When a user clicks a tract, show:
   - Top 3 complaint types
   - Median resolution time per type vs. citywide
   - Worst building (BBL with most violations)
   - Council district + member name

   Turns the tool from "finger-pointing index" into something a council office can use.

8. **Alternate ML targets.**
   Currently the RF predicts the composite score. More granular: predict each subcomponent independently and report which dimension is the *outlier* per tract. ("This tract's accountability gap is 2× expected — that's where the unexplained neglect lives.")

9. **Model explainability per tract.**
   SHAP values on the RF. For any tract, show which demographics pushed the prediction up vs. down. Lets a user audit "why does the model expect this tract to score X?"

10. **Comparison cohort tool.**
    Pick a tract → app shows the 10 most demographically similar tracts (k-NN in feature space). If the chosen tract has a much higher residual than its cohort, that's a strong claim.

### Long-term (research-quality extensions)

11. **Causal-inference layer.**
    Use difference-in-differences or matched cohorts to test whether specific interventions (council-funded inspections, tenant lawyer programs, NYCHA capital projects) reduce risk score in their target tracts vs. matched controls. The residual map identifies treatment vs. control candidates.

12. **Local Moran's I hotspot detection.**
    Global Moran's I on residuals is +0.194 after controlling for demographics and building stock — statistically significant clustering exists. Local Moran's I (LISA) would identify specific contiguous clusters of high-residual tracts ("neglect hotspots") for targeted reporting. libpysal's `esda.Moran_Local` runs on the same spatial weights matrix already built for validation.

13. **Building-level risk score.**
    Drop the tract aggregation entirely and compute a per-BBL or per-BIN risk score. Tract is a coarse unit; one block can contain very different buildings. HPD violations are already at building level.

14. **Open API.**
    Expose `/api/tract/<GEOID>` returning the risk score, residual, top complaints, and trend data as JSON. Useful for journalists, tenant orgs, and researchers who don't want to install the stack.

15. **Alternate severity weightings — A/B/C breakdown.**
    Currently filters to Class C violations. Class A (least serious) and Class B (intermediate) carry different signals. A multi-class severity composite could replace the binary "Class C only" filter.

16. **Geographic generalization.**
    The pipeline assumes NYC schemas (HPD, 311, NYC tract shapefile). Refactoring `load_and_clean.py` into a config-driven loader would let it run against Chicago, LA, etc. — comparison across cities would be a major contribution.

### Speculative

17. **LLM-generated tract narratives.**
    Per high-residual tract, compose a 3-sentence summary by feeding the metric profile to an LLM. ("Bedford-Stuyvesant tract X has a closure time 2.5× the city average and a vacate rate in the top decile, despite a poverty rate near the city median. The dominant complaint type is heat/hot water.") Surfaces the *pattern* without requiring users to read seven numbers.

18. **Predictive: which tracts are about to deteriorate?**
    Frame as a forecasting problem — given trailing-12-month features, predict next-quarter score. Identify leading indicators (e.g. spikes in mold complaints precede vacate orders by 6 months). Would require a meaningfully longer time series than 2024-present.

---

## What This Project Is Not

- **Not a causal claim.** Demographics correlate with neglect; neglect correlates with residuals. None of this proves *why*.
- **Not a comprehensive neglect index.** Only housing-related signals. Sanitation, transit, parks, schools — all absent.
- **Not real-time.** Pipeline must be re-run when data refreshes; no streaming ingestion.
- **Not validated against ground truth** (yet — see future item #1).

The contribution is **decomposing** observed neglect into "what poverty predicts" vs. "what's left over." The residual map is the part that earns the project's existence.
