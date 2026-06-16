import { useEffect, useState } from "react";
import { api } from "../api";
import type { MetricComparison, TractDetail, TractTimeSeries } from "../types";
import { Sparkline, TrendBadge, trend } from "./Sparkline";

const BAND_CLASS = { high: "band-high", elevated: "band-elevated", low: "band-low" };

function formatMetric(key: string, value: number | null, unit: string): string {
  if (value == null) return "N/A";
  switch (key) {
    case "median_income":
      return `$${Math.round(value).toLocaleString()}`;
    case "avg_closure_time":
      return `${value.toFixed(1)}${unit}`;
    case "accountability_gap":
      return value.toFixed(2);
    case "weighted_violation_rate":
      return value.toFixed(3);
    case "vacate_rate":
      return value.toFixed(4);
    default:
      return `${value.toFixed(2)}${unit}`;
  }
}

type TrendMode = "risk_score" | "risk_residual";

function TrendSection({ series }: { series: TractTimeSeries }) {
  const hasResidual =
    series.risk_residual != null && series.risk_residual.some((v) => v != null);
  const [mode, setMode] = useState<TrendMode>("risk_score");
  const isResidual = mode === "risk_residual" && hasResidual;

  const values = isResidual ? series.risk_residual! : series.risk_score;
  const t = trend(series.quarters, values);
  if (!t) return null; // fewer than two scored quarters — nothing to trend

  // risk_score is a 0–100 percentile; a residual gets a symmetric range around 0.
  const domain: [number, number] = isResidual
    ? (() => {
        const m = Math.max(10, ...values.map((v) => Math.abs(v ?? 0)));
        return [-m, m];
      })()
    : [0, 100];

  return (
    <div className="trend">
      <div className="trend-head">
        <span className="trend-title">
          {isResidual ? "Residual trend" : "Risk-score trend"}
        </span>
        {hasResidual && (
          <div className="seg seg-sm">
            <button
              className={!isResidual ? "active" : ""}
              onClick={() => setMode("risk_score")}
            >
              Score
            </button>
            <button
              className={isResidual ? "active" : ""}
              onClick={() => setMode("risk_residual")}
            >
              vs. prediction
            </button>
          </div>
        )}
      </div>
      <Sparkline
        quarters={series.quarters}
        values={values}
        domain={domain}
        baseline={isResidual ? 0 : undefined}
        color={isResidual ? "var(--muted)" : "var(--accent)"}
        label={isResidual ? "Residual" : "Risk score"}
      />
      <div className="legend-ends">
        <span>{t.firstQuarter}</span>
        <span className="trend-summary">
          <TrendBadge t={t} /> over {series.quarters.length} quarters
        </span>
        <span>{t.lastQuarter}</span>
      </div>
      <div className="legend-note" style={{ marginTop: 6 }}>
        {isResidual
          ? "Points vs. the demographic prediction (held-fixed model). Above 0 = more underserved than demographics predict."
          : "Within-quarter percentile rank (0–100). The line tracks relative neglect over time, not absolute counts."}
      </div>
    </div>
  );
}

function MetricRow({ m }: { m: MetricComparison }) {
  return (
    <div className="metric-box">
      <div className="metric-label">{m.label}</div>
      <div className="metric-value">{formatMetric(m.key, m.value, m.unit)}</div>
      {m.ratio != null && m.direction && (
        <div className="metric-compare">
          {m.ratio.toFixed(1)}× {m.direction} than city avg
        </div>
      )}
    </div>
  );
}

export function DetailCard({ geoid, onClose }: { geoid: string; onClose: () => void }) {
  const [detail, setDetail] = useState<TractDetail | null>(null);
  const [series, setSeries] = useState<TractTimeSeries | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setDetail(null);
    setSeries(null);
    setError(null);
    api.tract(geoid).then(setDetail).catch((e) => setError(String(e)));
    // Optional: 404s (no series, or a bundle without timeseries) resolve to null.
    api.timeseries(geoid).then(setSeries).catch(console.error);
  }, [geoid]);

  return (
    <div className="card detail">
      <button className="close" onClick={onClose} aria-label="Close">
        ✕
      </button>
      {error && <div className="error">{error}</div>}
      {!detail && !error && <div className="loading">Loading…</div>}
      {detail && (
        <>
          <div className="tract-name">{detail.neighborhood ?? "Unknown"}</div>
          <div className="tract-boro">
            {detail.borough}
            {detail.council_district != null && ` · District ${detail.council_district}`}
          </div>
          <div className="tract-id">Tract {detail.geoid}</div>

          <div className="score-big">
            <div className={`v ${BAND_CLASS[detail.band]}`}>
              {detail.risk_score?.toFixed(1) ?? "—"}
            </div>
            <div className="l">Underservice Risk Score</div>
          </div>

          {detail.interpretation && (
            <div className="legend-note" style={{ textAlign: "center", marginTop: 0 }}>
              {detail.interpretation}
            </div>
          )}

          {series && <TrendSection series={series} />}

          <div className="divider" />
          {detail.metrics.map((m) => (
            <MetricRow key={m.key} m={m} />
          ))}
        </>
      )}
    </div>
  );
}
