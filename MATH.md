# Math in the Underservice Risk Pipeline

Walking through every transformation, in order of pipeline execution.

> **Math rendering:** display equations use GitHub's fenced ` ```math ` blocks and
> inline expressions use `$…$`; both render on github.com and in most Markdown
> viewers with MathJax/KaTeX support.

---

## 1. Per-tract aggregation (`pipeline/aggregate.py`)

### 1a. Complaint-type normalization of closure time

Different housing complaints have different intrinsic resolution times (heat: days; mold: months). Raw `closure_time_days` per tract conflates *agency speed* with *complaint mix*. Fix:

For each 311 record $i$ of complaint type $t$:

```math
\text{closure\_ratio}_i = \frac{\text{closure\_time\_days}_i}{\text{median}_t(\text{closure\_time\_days})}
```

Then the per-tract `avg_closure_ratio` is the simple mean of those ratios. A value of $1.0$ means "exactly typical for this tract's complaint mix"; $1.5$ means "50% slower than typical."

### 1b. Rates per tract

Three population/unit-normalized rates:

```math
\text{complaint\_rate} = \frac{\text{complaint\_count}}{\text{population}}, \quad
\text{violation\_rate} = \frac{\text{HPD\_class\_C\_count}}{\text{housing\_units}}, \quad
\text{vacate\_rate} = \frac{\text{vacated\_units}}{\text{housing\_units}}
```

### 1c. Income-adjusted complaint rate (OLS residualization)

Wealthier tracts file more 311s per capita, biasing the accountability gap downward in gentrifying tracts. Fit an OLS model:

```math
\text{complaint\_rate} = \beta_0 + \beta_1 \log(\text{median\_income}) + \varepsilon
```

then take residuals and re-center on the citywide mean of complaint rate $\bar{c}$:

```math
\text{complaint\_rate\_adjusted} = \max\!\left(10^{-4},\; (y - \hat{y}) + \bar{c}\right)
```

The recentering preserves units (still "complaints per resident") so downstream ratios remain interpretable. The clipping floor of $10^{-4}$ avoids division-by-zero in the next step.

### 1d. Triage-adjusted closure ratio (OLS residualization)

HPD prioritizes high-violation tracts, so they get artificially fast responses. To strip that out, fit:

```math
\text{avg\_closure\_ratio} = \gamma_0 + \gamma_1 \cdot \text{violation\_rate} + \varepsilon
```

and again residualize and recenter on the citywide mean $\bar{r}$:

```math
\text{avg\_closure\_time\_adjusted} = \max\!\left(10^{-4},\; (y - \hat{y}) + \bar{r}\right)
```

After this, the value answers: *"Is the city slower here than triage alone would predict?"*

### 1e. Severity-weighted violation rate

```math
\text{weighted\_violation\_rate} = \text{violation\_rate} \cdot (1 + \text{vacate\_rate})
```

The $(1 + x)$ form means the weighting smoothly multiplies up tracts where violations escalated to vacate orders, without zeroing out tracts with no vacate orders.

### 1f. Accountability gap

```math
\text{accountability\_gap} = \frac{\text{weighted\_violation\_rate}}{\text{complaint\_rate\_adjusted} + 0.001}
```

The $+0.001$ regularizer prevents division blow-up in the handful of tracts where adjusted complaint rate is near zero. High values = "violations exist but residents aren't filing 311s" (silent neglect).

### 1g. PLUTO aggregations (per tract, across residential lots $L$)

```math
\text{median\_year\_built} = \text{median}_{\ell \in L}(\text{yearbuilt}_\ell)
```

```math
\text{pct\_prewar\_units} = \frac{\sum_{\ell : \text{year}_\ell < 1947} \text{unitsres}_\ell}{\sum_\ell \text{unitsres}_\ell}, \quad \text{clipped to }[0,1]
```

```math
\text{pct\_rent\_stab\_proxy} = \frac{\sum_{\ell : \text{year}_\ell < 1974\,\wedge\,\text{units}_\ell \ge 6} \text{unitsres}_\ell}{\sum_\ell \text{unitsres}_\ell}, \quad \text{clipped to }[0,1]
```

The 1947 cutoff is the NYC Multiple Dwelling Law "old-law" threshold; 1974 + 6-unit minimum is the ETPA rent-stabilization presumption.

---

## 2. Rank composite → risk score (`pipeline/regression.py`)

For each of the four composite features (`accountability_gap`, `weighted_violation_rate`, `avg_closure_time_adjusted`, `vacate_rate`), convert to a **percentile rank** in $[0, 1]$ across all valid tracts:

```math
r_f(i) = \frac{\text{rank of tract } i \text{ on feature } f}{N}
```

Then the weighted average with fixed weights $w = (0.40, 0.30, 0.20, 0.10)$:

```math
\text{risk\_score}(i) = 100 \cdot \frac{\sum_f w_f \cdot r_f(i)}{\sum_f w_f}
```

The percentile transform makes the composite scale-invariant: outlier tracts on any single feature can't dominate the score (a tract at the 99th percentile on accountability gap contributes the same $0.99 \cdot 0.40 = 0.396$ regardless of how extreme its raw value is).

---

## 3. Random Forest demographic decomposition (`pipeline/demographic_analysis.py`)

### 3a. Model

Random Forest regressor with 300 trees, $\min_{\text{leaf}} = 3$, no max depth. Features = 12 demographic + building-stock variables; target = `risk_score`.

A single regression tree partitions feature space recursively, choosing each split $(j, s)$ to minimize **weighted variance** of the target in the resulting children:

```math
\min_{j,s}\; \frac{|L|}{|N|} \text{Var}(y_L) + \frac{|R|}{|N|} \text{Var}(y_R)
```

The forest averages predictions over 300 such trees, each trained on a bootstrap sample of rows with a random subset of features considered at each split.

### 3b. Train/test evaluation

80/20 random split, then:

```math
R^2 = 1 - \frac{\sum_i (y_i - \hat{y}_i)^2}{\sum_i (y_i - \bar{y})^2}, \qquad \text{RMSE} = \sqrt{\frac{1}{n}\sum_i (y_i - \hat{y}_i)^2}
```

Current values: $R^2 = 0.748$, RMSE $= 10.4$ points.

### 3c. Residuals (the actual deliverable)

For inference, use **5-fold cross-validated predictions** (each tract's prediction comes from a model that didn't see it during training):

```math
\text{predicted\_risk}(i) = \hat{y}_i^{(\text{CV})}, \qquad \text{risk\_residual}(i) = y_i - \hat{y}_i^{(\text{CV})}
```

Positive residual = more underserved than demographics + building age would predict.

### 3d. Feature importance

Per feature $j$:

```math
\text{importance}(j) = \frac{1}{|T|}\sum_{t \in T}\;\sum_{\text{nodes } v \in t,\; \text{split}(v) = j} \frac{|S_v|}{N} \cdot \Delta\text{Var}(v)
```

i.e. average across trees of the impurity (variance) reduction at each split that uses feature $j$, weighted by the fraction of samples reaching that node. Importances sum to 1.

### 3e. Pearson correlation reporting

Standard:

```math
\rho_{X,Y} = \frac{\sum_i (x_i - \bar{x})(y_i - \bar{y})}{\sqrt{\sum_i (x_i - \bar{x})^2}\sqrt{\sum_i (y_i - \bar{y})^2}}
```

Used as a sanity check before fitting the forest — confirms feature directions match intuition (income negatively correlated with risk, etc.).

---

## 4. Validation suite math (`validation/`)

### 4a. Temporal split (`test_temporal_split.py`)

Compute the risk score using only HPD violations dated *before* a cutoff. Then for each tract count post-cutoff violations and form `post_rate = post_violations / housing_units`. Spearman rank correlation between pre-cutoff risk and post-cutoff rate:

```math
\rho_S = \text{Pearson correlation of}\;(\text{rank}(x),\, \text{rank}(y))
```

Quintile ratio: split tracts into 5 equal-size buckets by pre-cutoff risk; report the ratio of mean post-rate in the top vs. bottom quintile.

The leave-one-out variant (`test_temporal_split_leave_one_out.py`) rebuilds the composite *without* `weighted_violation_rate` (which shares its source with the post-cutoff outcome) to check that predictive validity isn't just HPD-on-HPD autocorrelation.

### 4b. Bootstrap CIs (`test_bootstrap_ci.py`)

For $b = 1, \dots, B$:
1. Resample joined-311, joined-HPD, joined-vacate records *with replacement* (each at frac=1.0)
2. Re-aggregate and re-score → $s^{(b)}_i$ for each tract $i$

Per-tract 90% percentile interval:

```math
\text{CI}_{90\%}(i) = \left[\,\text{quantile}_{0.05}(s^{(b)}_i),\;\text{quantile}_{0.95}(s^{(b)}_i)\,\right]
```

### 4c. Weight sensitivity (`test_weight_sensitivity.py`)

For trial $i$, draw a perturbed weight vector from a Dirichlet centered on the base weights:

```math
w^{(i)} \sim \text{Dirichlet}(\alpha \cdot w_{\text{base}})
```

with concentration $\alpha = 50$ (higher = tighter around base). Recompute the composite, then compare orderings via **Kendall's $\tau$**:

```math
\tau = \frac{(\text{concordant pairs}) - (\text{discordant pairs})}{\binom{n}{2}}
```

Median $\tau$ across 1000 draws answers: "would my conclusions change if I'd picked the weights differently?"

### 4d. Moran's I — spatial autocorrelation of residuals (`test_spatial_residuals.py`)

Build a spatial weights matrix $W$ from k-nearest-neighbors ($k=6$, row-standardized so each row sums to 1). Then:

```math
I = \frac{N}{\sum_{i,j} w_{ij}} \cdot \frac{\sum_i \sum_j w_{ij}\,(z_i - \bar{z})(z_j - \bar{z})}{\sum_i (z_i - \bar{z})^2}
```

where $z_i$ is the residual for tract $i$. Range: $\approx -1$ (perfect anti-clustering) to $+1$ (perfect clustering). Expected value under spatial randomness: $E[I] = -1/(N-1) \approx 0$.

P-value via **conditional permutation**: shuffle residual values 999 times across tract locations, compute $I$ each time, count fraction of permutations with $|I^{(\text{perm})}| \ge |I^{(\text{obs})}|$. Current observed $I = +0.19$ — the residuals still cluster, which is interpreted as institutional geography (neglect propagating along enforcement boundaries) rather than missing demographic features.

---

## Summary of techniques used

| Step | Technique |
|---|---|
| 1a | Per-category median normalization |
| 1c, 1d | OLS residualization with mean-recentering |
| 1e | Multiplicative severity weighting |
| 1g | Weighted ratios with clipping |
| 2 | Percentile-rank weighted composite |
| 3a | Random Forest (variance-reducing splits, bagging) |
| 3b | Hold-out $R^2$, RMSE |
| 3c | 5-fold cross-validated residuals |
| 3d | Mean decrease in impurity (MDI) |
| 4a | Spearman $\rho$, quintile ratio |
| 4b | Nonparametric percentile bootstrap |
| 4c | Dirichlet sampling, Kendall's $\tau$ |
| 4d | Moran's I with KNN weights and permutation inference |

The core philosophy: **don't model what you can normalize away.** Each OLS residualization (income, triage) and each per-category normalization (complaint type) strips a known confound *before* the data hits the composite, so the rank composite itself stays simple — just weighted percentile averages — and the Random Forest is reserved for the irreducible demographic-vs-institutional decomposition.
