import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import type { ModelInfo, PredictResponse } from "../types";

const BAND_CLASS = { high: "band-high", elevated: "band-elevated", low: "band-low" };

function fmt(v: number, max: number): string {
  return max > 1000 ? Math.round(v).toLocaleString() : v.toFixed(3);
}

export function Predictor({ model }: { model: ModelInfo | null }) {
  const [inputs, setInputs] = useState<Record<string, number>>({});
  const [pred, setPred] = useState<PredictResponse | null>(null);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => {
    if (!model) return;
    const init: Record<string, number> = {};
    for (const f of model.features) init[f] = model.feature_ranges[f].median;
    setInputs(init);
  }, [model]);

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

  return (
    <>
      <h2>Predict Risk Score from Demographics</h2>
      <p className="sub">
        Random Forest trained on demographic + building-stock features. Held-out R² ={" "}
        <b>{model.r2.toFixed(2)}</b>, RMSE = <b>{model.rmse.toFixed(1)}</b> points. Drag the
        sliders to see the model's predicted risk for a hypothetical tract.
      </p>

      {pred && (
        <div className="pred-result">
          <div className="l">Predicted Risk Score</div>
          <div className={`v ${BAND_CLASS[pred.band]}`}>{pred.predicted_risk.toFixed(1)}</div>
        </div>
      )}

      <div className="slider-grid">
        {model.features.map((f) => {
          const r = model.feature_ranges[f];
          const val = inputs[f] ?? r.median;
          return (
            <div className="slider-box" key={f}>
              <div className="s-top">
                <span>{model.labels[f] ?? f}</span>
                <span className="sv">{fmt(val, r.max)}</span>
              </div>
              <input
                type="range"
                min={r.min}
                max={r.max}
                step={(r.max - r.min) / 100 || 1}
                value={val}
                onChange={(e) =>
                  setInputs((cur) => ({ ...cur, [f]: Number(e.target.value) }))
                }
              />
            </div>
          );
        })}
      </div>

      <h3 style={{ marginTop: 28 }}>Feature importance</h3>
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
