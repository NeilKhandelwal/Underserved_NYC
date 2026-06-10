import { useEffect, useState } from "react";
import { api } from "../api";
import type { MetricComparison, TractDetail } from "../types";

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
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setDetail(null);
    setError(null);
    api.tract(geoid).then(setDetail).catch((e) => setError(String(e)));
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

          <div className="divider" />
          {detail.metrics.map((m) => (
            <MetricRow key={m.key} m={m} />
          ))}
        </>
      )}
    </div>
  );
}
