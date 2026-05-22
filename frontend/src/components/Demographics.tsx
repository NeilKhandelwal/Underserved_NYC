import { useEffect, useState } from "react";
import { api } from "../api";
import type { Correlation } from "../types";

export function Demographics() {
  const [rows, setRows] = useState<Correlation[]>([]);

  useEffect(() => {
    api.correlations().then(setRows).catch(console.error);
  }, []);

  const max = Math.max(1e-6, ...rows.map((r) => Math.abs(r.r)));

  return (
    <>
      <h2>Demographics vs. Risk Score</h2>
      <p className="sub">
        Pearson correlation between each demographic / building-stock feature and the
        underservice risk score, sorted by magnitude. Positive (red) = higher values
        coincide with higher risk; negative (teal) = protective.
      </p>
      <div className="bars">
        {rows.map((r) => {
          const pct = (Math.abs(r.r) / max) * 100;
          const pos = r.r >= 0;
          return (
            <div className="bar-row" key={r.column}>
              <div className="lbl">{r.label}</div>
              <div className="bar-track">
                <div
                  className="bar-fill"
                  style={{ width: `${pct}%`, background: pos ? "var(--red)" : "var(--teal)" }}
                />
              </div>
              <div className="val">{r.r >= 0 ? "+" : ""}{r.r.toFixed(3)}</div>
            </div>
          );
        })}
      </div>
    </>
  );
}
