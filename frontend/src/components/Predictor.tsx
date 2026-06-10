import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import type { ModelInfo, PredictResponse } from "../types";

const BAND_CLASS = { high: "band-high", elevated: "band-elevated", low: "band-low" };
const BAND_LABEL = { high: "High (≥ 75)", elevated: "Elevated (50–75)", low: "Low (< 50)" };

// Per-feature display semantics. Most features are population fractions (0–1);
// the exceptions are dollars, calendar years, and ACS aggregate minutes.
const DOLLAR = new Set(["median_income"]);
const YEAR = new Set(["median_year_built"]);
const AGGREGATE_MIN = new Set(["mean_commute_time"]);

const HINTS: Record<string, string> = {
  mean_commute_time:
    "Total commute minutes summed over all workers in the tract (ACS B08013) — grows with tract size, not just commute length.",
  pct_rent_stab_proxy: "Share of units in pre-1974 buildings with 6+ units.",
};

function fmtFeature(f: string, v: number): string {
  if (DOLLAR.has(f)) return `$${Math.round(v).toLocaleString()}`;
  if (YEAR.has(f)) return String(Math.round(v));
  if (AGGREGATE_MIN.has(f)) return `${Math.round(v).toLocaleString()} min`;
  return `${(v * 100).toFixed(1)}%`;
}

function stepFor(f: string, min: number, max: number): number {
  if (YEAR.has(f)) return 1;
  if (DOLLAR.has(f) || AGGREGATE_MIN.has(f)) return 500;
  return (max - min) / 200 || 1; // fractions: fine-grained
}

export function Predictor({ model }: { model: ModelInfo | null }) {
  const [inputs, setInputs] = useState<Record<string, number>>({});
  const [pred, setPred] = useState<PredictResponse | null>(null);
  const [baseline, setBaseline] = useState<number | null>(null);
  const timer = useRef<number | undefined>(undefined);

  const medians = useMemo(() => {
    if (!model) return {};
    const init: Record<string, number> = {};
    for (const f of model.features) init[f] = model.feature_ranges[f].median;
    return init;
  }, [model]);

  useEffect(() => {
    if (!model) return;
    setInputs(medians);
    // Prediction for an all-medians tract, used as the comparison baseline.
    api.predict({}).then((r) => setBaseline(r.predicted_risk)).catch(console.error);
  }, [model, medians]);

  useEffect(() => {
    if (Object.keys(inputs).length === 0) return;
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      api.predict(inputs).then(setPred).catch(console.error);
    }, 120);
    return () => window.clearTimeout(timer.current);
  }, [inputs]);

  const importance = useMemo(() => {
    if (!model) return [];
    return Object.entries(model.importance).sort((a, b) => b[1] - a[1]);
  }, [model]);

  if (!model) return <div className="loading">Loading model…</div>;
  const maxImp = Math.max(...importance.map(([, v]) => v));
  const isDefault = model.features.every((f) => (inputs[f] ?? medians[f]) === medians[f]);
  const delta = pred && baseline != null ? pred.predicted_risk - baseline : null;

  return (
    <>
      <h2>Predict Risk Score from Demographics</h2>
      <p className="sub">
        Random Forest trained on demographic + building-stock features. Held-out R² ={" "}
        <b>{model.r2.toFixed(2)}</b>, RMSE = <b>{model.rmse.toFixed(1)}</b> points — so any
        single prediction is roughly ±{Math.round(model.rmse)} points. Sliders start at the
        citywide median tract; drag them to describe a hypothetical tract.
      </p>

      {pred && (
        <div className="pred-result">
          <div className="l">Predicted Risk Score</div>
          <div className={`v ${BAND_CLASS[pred.band]}`}>{pred.predicted_risk.toFixed(1)}</div>
          <div className={`pred-band ${BAND_CLASS[pred.band]}`}>{BAND_LABEL[pred.band]}</div>
          {delta != null && Math.abs(delta) >= 0.05 && (
            <div className="pred-delta">
              {delta > 0 ? "+" : ""}
              {delta.toFixed(1)} vs. the citywide-median tract ({baseline!.toFixed(1)})
            </div>
          )}
          <div className="band-scale" aria-hidden>
            <div className="seg-low" />
            <div className="seg-elevated" />
            <div className="seg-high" />
            <div
              className="band-marker"
              style={{ left: `${Math.min(100, Math.max(0, pred.predicted_risk))}%` }}
            />
          </div>
          <div className="band-scale-labels">
            <span style={{ left: 0 }}>0</span>
            <span style={{ left: "50%" }}>50</span>
            <span style={{ left: "75%" }}>75</span>
            <span style={{ left: "100%" }}>100</span>
          </div>
        </div>
      )}

      <div className="slider-head">
        <h3>Tract characteristics</h3>
        <button className="reset-btn" disabled={isDefault} onClick={() => setInputs(medians)}>
          Reset to citywide medians
        </button>
      </div>

      <div className="slider-grid">
        {model.features.map((f) => {
          const r = model.feature_ranges[f];
          const val = inputs[f] ?? r.median;
          return (
            <div className="slider-box" key={f}>
              <div className="s-top">
                <span>{model.labels[f] ?? f}</span>
                <span className="sv">{fmtFeature(f, val)}</span>
              </div>
              <input
                type="range"
                min={r.min}
                max={r.max}
                step={stepFor(f, r.min, r.max)}
                value={val}
                onChange={(e) =>
                  setInputs((cur) => ({ ...cur, [f]: Number(e.target.value) }))
                }
              />
              <div className="s-range">
                <span>{fmtFeature(f, r.min)}</span>
                {val !== r.median && <span className="s-med">median {fmtFeature(f, r.median)}</span>}
                <span>{fmtFeature(f, r.max)}</span>
              </div>
              {HINTS[f] && <div className="s-hint">{HINTS[f]}</div>}
            </div>
          );
        })}
      </div>

      <h3 style={{ marginTop: 28 }}>Feature importance</h3>
      <p className="sub" style={{ marginBottom: 12 }}>
        How much each feature contributes to the Random Forest's predictions (shares sum
        to 100%). Importance is not direction — see the Demographics tab for whether a
        feature tracks higher or lower risk.
      </p>
      <div className="bars">
        {importance.map(([f, v]) => (
          <div className="bar-row" key={f}>
            <div className="lbl">{model.labels[f] ?? f}</div>
            <div className="bar-track">
              <div
                className="bar-fill"
                style={{ width: `${(v / maxImp) * 100}%`, background: "var(--accent)" }}
              />
            </div>
            <div className="val">{(v * 100).toFixed(1)}%</div>
          </div>
        ))}
      </div>
    </>
  );
}
