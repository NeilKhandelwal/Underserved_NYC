export function Methodology() {
  return (
    <div className="prose">
      <h2>Methodology</h2>
      <p className="sub">
        The Underservice Risk Score (0–100) ranks every NYC census tract on four independent
        indicators of housing-related municipal neglect, then averages their percentile ranks
        using fixed weights. A tract scoring 80 ranks in the top 20% on most dimensions.
      </p>

      <h3>Composite inputs</h3>
      <table>
        <thead>
          <tr><th>Input</th><th>Weight</th><th>What it measures</th></tr>
        </thead>
        <tbody>
          <tr>
            <td><b>Accountability Gap</b></td><td>40%</td>
            <td>HPD Class C violations ÷ 311 complaint rate. High = serious violations
              accumulate while residents don't (or can't) report them — silent neglect.</td>
          </tr>
          <tr>
            <td><b>Severity-Weighted Violation Rate</b></td><td>30%</td>
            <td>Class C violations per housing unit × (1 + vacate rate). Distinguishes "many
              minor issues" from "buildings declared uninhabitable."</td>
          </tr>
          <tr>
            <td><b>Avg 311 Closure Time</b></td><td>20%</td>
            <td>How long housing complaints take to close (2024–present, auto-closes excluded).
              Double-corrected for complaint type and triage.</td>
          </tr>
          <tr>
            <td><b>Vacate Order Rate</b></td><td>10%</td>
            <td>Vacated units per housing unit. Independent severity check.</td>
          </tr>
        </tbody>
      </table>

      <h3>The residual is the point</h3>
      <p>
        Mapping any housing-stress signal in NYC mostly reproduces the poverty map. So a Random
        Forest is fit to predict the risk score from 12 demographic and building-stock features
        (ACS + PLUTO). The <b>residual</b> — actual risk minus what the model predicts — is the
        index of interest: a positive residual flags a tract that is <i>more underserved than
        its demographics alone would suggest</i>. After controlling for all 12 features the
        residuals still cluster geographically (Moran's I = +0.194), which points to
        institutional rather than purely structural causes.
      </p>

      <h3>Bias corrections</h3>
      <p>
        <b>Income-adjusted complaint rate</b> — wealthier tracts file more 311s per capita;
        <code>complaint_rate</code> is residualized against <code>log(median_income)</code> so
        gentrification doesn't deflate the accountability gap.
      </p>
      <p>
        <b>Complaint-type normalization</b> — heat complaints close in days, mold in months;
        each complaint's closure time is divided by the citywide median for its type.
      </p>
      <p>
        <b>Triage residualization</b> — HPD prioritizes high-violation buildings, so the worst
        tracts get artificially fast responses; the type-normalized closure ratio is
        residualized against <code>violation_rate</code> and re-centered.
      </p>

      <h3>What this is not</h3>
      <p>
        Descriptive, not causal. Housing signals only. A static 2024–present snapshot. The
        residual identifies <i>unexplained</i> variance, not its cause.
      </p>
    </div>
  );
}
